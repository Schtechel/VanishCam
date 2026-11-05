import AppKit
import Darwin
import AVFoundation
import CryptoKit

struct CameraProfile: Codable {
    var mode: String = ""
    var zoom: Double = 1
    var horizontal: Double = 0
    var vertical: Double = 0
}

struct CameraPreferences: Codable {
    var selectedID: String = ""
    var profiles: [String: CameraProfile] = [:]
}

func isSupportedCamera(_ name: String) -> Bool {
    let name = name.lowercased()
    return name == "camo camera" || name.contains("logitech")
        || name.contains("facetime") || name.contains("built-in")
}

@main
struct VanishCamMenu {
    static func main() {
        let root = Bundle.main.bundleURL.deletingLastPathComponent().deletingLastPathComponent()
        let engine = Bundle.main.resourceURL!.appendingPathComponent("Engine/VanishCamEngine")
        if CommandLine.arguments.contains("--self-test") {
            let packaged = FileManager.default.isExecutableFile(atPath: engine.path)
            guard packaged || FileManager.default.isExecutableFile(atPath: root.appendingPathComponent("VanishCam.command").path) else {
                fputs("VanishCam launcher is missing or not executable.\n", stderr)
                exit(1)
            }
            let child = Process()
            child.executableURL = packaged ? engine : URL(fileURLWithPath: "/bin/bash")
            child.arguments = packaged ? ["--self-test"] : [root.appendingPathComponent("VanishCam.command").path, "--self-test"]
            child.standardInput = FileHandle.nullDevice
            do {
                try child.run()
                child.waitUntilExit()
            } catch {
                fputs("Cannot run the VanishCam launcher: \(error.localizedDescription)\n", stderr)
                exit(1)
            }
            guard child.terminationStatus == 0 else {
                exit(child.terminationStatus)
            }
            print(packaged ? "VanishCam app and bundled engine verified." : "Development launcher and offline child process verified.")
            return
        }
        if NSRunningApplication.runningApplications(withBundleIdentifier: "local.vanishcam.menubar")
            .contains(where: { $0.processIdentifier != getpid() }) {
            return
        }
        let app = NSApplication.shared
        let delegate = MenuDelegate(root: root)
        app.delegate = delegate
        app.setActivationPolicy(.regular)
        app.run()
    }
}

final class MenuDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private let root: URL
    private var statusItem: NSStatusItem!
    private var startItem: NSMenuItem!
    private var stopItem: NSMenuItem!
    private var showMyselfItem: NSMenuItem!
    private var process: Process?
    private var logHandle: FileHandle?
    private var stopping = false
    private var quitting = false
    private var controlsWindow: NSWindow?
    private var startButton: NSButton?
    private var stopButton: NSButton?
    private var showMyselfButton: NSButton?
    private var effectButtons: [NSButton] = []
    private var previewView: NSImageView?
    private var statusLabel: NSTextField?
    private var previewPipe: Pipe?
    private var stopTimeout: DispatchWorkItem?
    private var cameras: [AVCaptureDevice] = []
    private var preferences = CameraPreferences()
    private var cameraPicker: NSPopUpButton?
    private var modePicker: NSPopUpButton?
    private var refreshButton: NSButton?
    private var zoomSlider: NSSlider?
    private var horizontalSlider: NSSlider?
    private var verticalSlider: NSSlider?
    private var framingLabel: NSTextField?
    private var effectsToggle: NSButton?
    private var gesturesToggle: NSButton?
    private var resetButton: NSButton?
    private var resetMenuItem: NSMenuItem?
    private var backgroundReady = false
    private var effectsMenuItem: NSMenuItem?
    private var gesturesMenuItem: NSMenuItem?
    private var effectMenuItems: [NSMenuItem] = []
    private var hidePreviewItem: NSMenuItem?

    @objc private func toggleMenuEffects() {
        effectsToggle?.state = effectsToggle?.state == .on ? .off : .on
        callControlsChanged()
    }

    @objc private func toggleMenuGestures() {
        gesturesToggle?.state = gesturesToggle?.state == .on ? .off : .on
        callControlsChanged()
    }

    @objc private func triggerMenuEffect(_ sender: NSMenuItem) {
        do { try sendKey(String(UnicodeScalar(sender.tag)!)) }
        catch { showError("Could not trigger effect", detail: error.localizedDescription) }
    }

    @objc private func hidePreview() {
        controlsWindow?.close()
    }

    func windowWillClose(_ notification: Notification) {
        if !CommandLine.arguments.contains("--ui-self-test") {
            UserDefaults.standard.set(false, forKey: "ShowControlsOnLaunch")
        }
        hidePreviewItem?.isEnabled = false
    }

    private func saveCallControls() throws {
        try FileManager.default.createDirectory(at: stateDirectory, withIntermediateDirectories: true)
        let data = try JSONSerialization.data(withJSONObject: [
            "effects": effectsToggle?.state == .on,
            "gestures": gesturesToggle?.state == .on
        ])
        try data.write(to: stateDirectory.appendingPathComponent("call-controls.json"), options: .atomic)
    }

    @objc private func callControlsChanged() {
        do {
            if effectsToggle?.state != .on { gesturesToggle?.state = .off }
            try saveCallControls()
            updateControls()
        } catch {
            showError("Could not change call controls", detail: error.localizedDescription)
        }
    }

    private var profileDirectory: URL {
        let digest = SHA256.hash(data: Data(preferences.selectedID.utf8))
            .map { String(format: "%02x", $0) }.joined()
        return stateDirectory.appendingPathComponent("cameras/\(digest)")
    }

    private var selectedCamera: AVCaptureDevice? {
        cameras.first { $0.uniqueID == preferences.selectedID }
    }

    private var selectedProfile: CameraProfile {
        preferences.profiles[preferences.selectedID] ?? CameraProfile()
    }

    private var backgroundURL: URL {
        let mode = selectedProfile.mode.replacingOccurrences(of: " @ ", with: "-")
        return profileDirectory.appendingPathComponent("background-\(mode).png")
    }

    private func supportedModes(_ camera: AVCaptureDevice) -> [String] {
        var modes = Set<String>()
        for format in camera.formats {
            let size = CMVideoFormatDescriptionGetDimensions(format.formatDescription)
            guard size.width >= 640 && size.height >= 480 && size.width <= 3840 else { continue }
            for fps in [30, 60] where format.videoSupportedFrameRateRanges.contains(where: {
                $0.minFrameRate <= Double(fps) + 0.01 && $0.maxFrameRate >= Double(fps) - 0.01
            }) {
                modes.insert("\(size.width)x\(size.height) @ \(fps)")
            }
        }
        return modes.sorted()
    }

    private func savePreferences() throws {
        try FileManager.default.createDirectory(at: stateDirectory, withIntermediateDirectories: true)
        try JSONEncoder().encode(preferences).write(to: stateDirectory.appendingPathComponent("cameras.json"), options: .atomic)
        try FileManager.default.createDirectory(at: profileDirectory, withIntermediateDirectories: true)
        let profile = selectedProfile
        let data = try JSONSerialization.data(withJSONObject: [
            "zoom": profile.zoom, "horizontal": profile.horizontal, "vertical": profile.vertical
        ])
        try data.write(to: profileDirectory.appendingPathComponent("framing.json"), options: .atomic)
    }

    @objc private func refreshCameras() {
        guard process == nil else { return }
        cameras = AVCaptureDevice.DiscoverySession(
            deviceTypes: [.builtInWideAngleCamera, .external],
            mediaType: .video, position: .unspecified
        ).devices.filter {
            isSupportedCamera($0.localizedName)
        }
        cameraPicker?.removeAllItems()
        if preferences.selectedID.isEmpty {
            preferences.selectedID = cameras.first(where: { $0.localizedName.lowercased().contains("logitech") })?.uniqueID
                ?? cameras.first?.uniqueID ?? ""
        }
        for camera in cameras {
            cameraPicker?.addItem(withTitle: camera.localizedName)
            cameraPicker?.lastItem?.representedObject = camera.uniqueID
        }
        if selectedCamera == nil {
            cameraPicker?.addItem(withTitle: "Saved camera unavailable — select another")
            cameraPicker?.lastItem?.representedObject = preferences.selectedID
        }
        if let item = cameraPicker?.itemArray.first(where: { ($0.representedObject as? String) == preferences.selectedID }) {
            cameraPicker?.select(item)
        }
        loadProfileControls()
        updateControls()
    }

    @objc private func cameraDevicesChanged() {
        DispatchQueue.main.async { [weak self] in self?.refreshCameras() }
    }

    @objc private func cameraChanged() {
        guard process == nil, let id = cameraPicker?.selectedItem?.representedObject as? String else { return }
        preferences.selectedID = id
        loadProfileControls()
        do { try savePreferences() }
        catch { showError("Could not save camera selection", detail: error.localizedDescription) }
        updateControls()
    }

    private func loadProfileControls() {
        var profile = selectedProfile
        let modes = selectedCamera.map(supportedModes) ?? []
        if !modes.isEmpty && !modes.contains(profile.mode) {
            profile.mode = modes.first(where: { $0 == "1920x1080 @ 30" })
                ?? modes.first(where: { $0 == "1280x720 @ 30" }) ?? modes.first ?? ""
        }
        preferences.profiles[preferences.selectedID] = profile
        modePicker?.removeAllItems()
        modePicker?.addItems(withTitles: modes)
        modePicker?.selectItem(withTitle: profile.mode)
        zoomSlider?.doubleValue = profile.zoom
        horizontalSlider?.doubleValue = profile.horizontal
        verticalSlider?.doubleValue = profile.vertical
        framingLabel?.stringValue = String(format: "Zoom %.2fx · position saved per camera", profile.zoom)
        statusLabel?.stringValue = selectedCamera == nil
            ? "Selected camera unavailable — choose another camera"
            : "Camera stopped — settings restored for \(selectedCamera!.localizedName)"
    }

    @objc private func settingsChanged() {
        var profile = selectedProfile
        profile.mode = modePicker?.titleOfSelectedItem ?? profile.mode
        profile.zoom = zoomSlider?.doubleValue ?? 1
        profile.horizontal = horizontalSlider?.doubleValue ?? 0
        profile.vertical = verticalSlider?.doubleValue ?? 0
        preferences.profiles[preferences.selectedID] = profile
        do {
            try savePreferences()
            framingLabel?.stringValue = String(format: "Zoom %.2fx · position saved per camera", profile.zoom)
        } catch {
            showError("Could not save camera settings", detail: error.localizedDescription)
        }
    }

    private var engineURL: URL {
        Bundle.main.resourceURL!.appendingPathComponent("Engine/VanishCamEngine")
    }

    private var packaged: Bool {
        FileManager.default.isExecutableFile(atPath: engineURL.path)
    }

    private var stateDirectory: URL {
        if packaged {
            return FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
                .appendingPathComponent("VanishCam")
        }
        return root.appendingPathComponent(".local-state")
    }

    init(root: URL) {
        self.root = root
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let preferenceURL = stateDirectory.appendingPathComponent("cameras.json")
        if FileManager.default.fileExists(atPath: preferenceURL.path) {
            do { preferences = try JSONDecoder().decode(CameraPreferences.self, from: Data(contentsOf: preferenceURL)) }
            catch { showError("Could not load camera settings", detail: error.localizedDescription) }
        }
        statusItem = NSStatusBar.system.statusItem(withLength: 40)
        statusItem.autosaveName = "VanishCamCamera"
        updateIcon(running: false)
        statusItem.button?.toolTip = "VanishCam is off"
        let menu = NSMenu()
        startItem = menu.addItem(withTitle: "Start VanishCam", action: #selector(start), keyEquivalent: "")
        startItem.target = self
        stopItem = menu.addItem(withTitle: "Stop VanishCam", action: #selector(stop), keyEquivalent: "")
        stopItem.target = self
        stopItem.isEnabled = false
        showMyselfItem = menu.addItem(withTitle: "Show myself", action: #selector(showMyself), keyEquivalent: "")
        showMyselfItem.target = self
        showMyselfItem.isEnabled = false
        let reset = menu.addItem(withTitle: "Reset background", action: #selector(resetBackground), keyEquivalent: "")
        reset.target = self
        resetMenuItem = reset
        if packaged {
            menu.addItem(.separator())
            let effects = menu.addItem(withTitle: "Enable effects", action: #selector(toggleMenuEffects), keyEquivalent: "")
            effects.target = self
            effectsMenuItem = effects
            let gestures = menu.addItem(withTitle: "Enable hand gestures", action: #selector(toggleMenuGestures), keyEquivalent: "")
            gestures.target = self
            gesturesMenuItem = gestures
            for (title, key) in [("Dissolve", 49), ("Naruto", 50), ("Goku", 51)] {
                let effect = menu.addItem(withTitle: title, action: #selector(triggerMenuEffect(_:)), keyEquivalent: "")
                effect.target = self
                effect.tag = key
                effectMenuItems.append(effect)
            }
            menu.addItem(.separator())
        }
        let controls = menu.addItem(withTitle: "Open controls", action: #selector(openControls), keyEquivalent: "")
        controls.target = self
        let hide = menu.addItem(withTitle: "Hide preview", action: #selector(hidePreview), keyEquivalent: "")
        hide.target = self
        hidePreviewItem = hide
        menu.addItem(.separator())
        let help = menu.addItem(withTitle: "How to use", action: #selector(showHelp), keyEquivalent: "")
        help.target = self
        let logs = menu.addItem(withTitle: "Open launch log", action: #selector(showLog), keyEquivalent: "")
        logs.target = self
        menu.addItem(.separator())
        let quit = menu.addItem(withTitle: "Quit VanishCam", action: #selector(quitApp), keyEquivalent: "q")
        quit.target = self
        statusItem.menu = menu
        menu.autoenablesItems = false
        let appMenu = NSMenu()
        let appMenuItem = NSMenuItem()
        appMenu.addItem(appMenuItem)
        let commands = NSMenu()
        commands.addItem(withTitle: "Open controls", action: #selector(openControls), keyEquivalent: "0").target = self
        commands.addItem(withTitle: "Open launch log", action: #selector(showLog), keyEquivalent: "l").target = self
        commands.addItem(withTitle: "Quit VanishCam", action: #selector(quitApp), keyEquivalent: "q").target = self
        appMenuItem.submenu = commands
        NSApplication.shared.mainMenu = appMenu
        showControls(show: CommandLine.arguments.contains("--ui-self-test")
                     || UserDefaults.standard.object(forKey: "ShowControlsOnLaunch") as? Bool != false)
        if packaged && !CommandLine.arguments.contains("--ui-self-test") {
            refreshCameras()
            for name in [AVCaptureDevice.wasConnectedNotification, AVCaptureDevice.wasDisconnectedNotification] {
                NotificationCenter.default.addObserver(self, selector: #selector(cameraDevicesChanged), name: name, object: nil)
            }
        }
        if CommandLine.arguments.contains("--ui-self-test") {
            guard isSupportedCamera("Camo Camera"), isSupportedCamera("Logitech BRIO"),
                  isSupportedCamera("FaceTime HD Camera"), !isSupportedCamera("OBS Virtual Camera") else {
                fputs("Camera input allowlist failed validation.\n", stderr)
                exit(1)
            }
            let before = controlsWindow!.frame.size
            previewView?.image = NSImage(size: NSSize(width: 1920, height: 1080))
            controlsWindow!.contentView!.layoutSubtreeIfNeeded()
            let preview = previewView!.frame.size
            print("Window before/after: \(before) / \(controlsWindow!.frame.size); preview: \(preview); effects: \(effectButtons.count); Start/Stop: \(startButton!.isEnabled)/\(stopButton!.isEnabled)")
            guard controlsWindow!.frame.size == before,
                  abs(preview.height - preview.width * 9.0 / 16.0) <= 1,
                  preview.width <= 632,
                  effectButtons.count == 3,
                  effectMenuItems.count == 3,
                  effectsMenuItem?.state == .off,
                  gesturesMenuItem?.isEnabled == false,
                  effectMenuItems.allSatisfy({ !$0.isEnabled }),
                  startButton!.isEnabled && !stopButton!.isEnabled else {
                fputs("Native preview layout or stopped controls failed validation.\n", stderr)
                exit(1)
            }
            let saved = preferences
            preferences.selectedID = "self-test-disconnected-camera"
            refreshCameras()
            guard selectedCamera == nil, !startButton!.isEnabled,
                  preferences.selectedID == "self-test-disconnected-camera" else {
                fputs("Disconnected camera silently fell back to another device.\n", stderr)
                exit(1)
            }
            preferences = saved
            refreshCameras()
            print("Native window verified: fixed widescreen preview, all controls, no camera opened.")
            print("Disconnected-camera selection verified: no automatic fallback.")
            NSApplication.shared.terminate(nil)
        }
    }

    @objc private func openControls() {
        showControls(show: true)
    }

    private func showControls(show: Bool) {
        if controlsWindow == nil {
            let window = NSWindow(
                contentRect: NSRect(x: 0, y: 0, width: 680, height: packaged ? 800 : 260),
                styleMask: [.titled, .closable, .miniaturizable],
                backing: .buffered, defer: false
            )
            window.title = "VanishCam controls"
            window.isReleasedWhenClosed = false
            window.delegate = self
            let stack = NSStackView()
            stack.orientation = .vertical
            stack.spacing = 10
            stack.edgeInsets = NSEdgeInsets(top: 20, left: 24, bottom: 20, right: 24)
            stack.translatesAutoresizingMaskIntoConstraints = false
            if packaged {
                let preview = NSImageView()
                preview.imageScaling = .scaleProportionallyUpOrDown
                preview.wantsLayer = true
                preview.layer?.backgroundColor = NSColor.black.cgColor
                preview.translatesAutoresizingMaskIntoConstraints = false
                stack.addArrangedSubview(preview)
                preview.widthAnchor.constraint(equalToConstant: 632).isActive = true
                preview.heightAnchor.constraint(equalTo: preview.widthAnchor, multiplier: 9.0 / 16.0).isActive = true
                preview.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
                preview.setContentCompressionResistancePriority(.defaultLow, for: .vertical)
                previewView = preview
            }
            let status = NSTextField(labelWithString: "Camera stopped")
            stack.addArrangedSubview(status)
            statusLabel = status
            if packaged {
                let effects = NSButton(checkboxWithTitle: "Enable effects", target: self, action: #selector(callControlsChanged))
                let gestures = NSButton(checkboxWithTitle: "Enable hand gestures", target: self, action: #selector(callControlsChanged))
                effectsToggle = effects
                gesturesToggle = gestures
                let callControls = NSStackView(views: [effects, gestures])
                callControls.spacing = 20
                stack.addArrangedSubview(callControls)
                let selection = NSStackView()
                selection.spacing = 12
                let picker = NSPopUpButton()
                picker.target = self
                picker.action = #selector(cameraChanged)
                cameraPicker = picker
                selection.addArrangedSubview(picker)
                let refresh = NSButton(title: "Refresh cameras", target: self, action: #selector(refreshCameras))
                refreshButton = refresh
                selection.addArrangedSubview(refresh)
                stack.addArrangedSubview(selection)
                let mode = NSPopUpButton()
                mode.target = self
                mode.action = #selector(settingsChanged)
                modePicker = mode
                let modeRow = NSStackView(views: [NSTextField(labelWithString: "Capture resolution / FPS"), mode])
                modeRow.spacing = 12
                stack.addArrangedSubview(modeRow)
                for (title, low, high, value) in [
                    ("Zoom", 1.0, 3.0, 1.0), ("Horizontal", -1.0, 1.0, 0.0), ("Vertical", -1.0, 1.0, 0.0)
                ] {
                    let slider = NSSlider(value: value, minValue: low, maxValue: high, target: self, action: #selector(settingsChanged))
                    slider.isContinuous = false
                    slider.widthAnchor.constraint(equalToConstant: 360).isActive = true
                    let row = NSStackView(views: [NSTextField(labelWithString: title), slider])
                    row.spacing = 12
                    stack.addArrangedSubview(row)
                    if title == "Zoom" { zoomSlider = slider }
                    if title == "Horizontal" { horizontalSlider = slider }
                    if title == "Vertical" { verticalSlider = slider }
                }
                let label = NSTextField(labelWithString: "")
                framingLabel = label
                stack.addArrangedSubview(label)
            }
            let note = NSTextField(wrappingLabelWithString: "Normal video keeps OBS live. Enable effects to use buttons; hand gestures are optional. Reset background only when ready to step out for four seconds. Stop disconnects video.")
            stack.addArrangedSubview(note)
            note.widthAnchor.constraint(equalToConstant: 632).isActive = true
            let controls = NSStackView()
            controls.spacing = 12
            for (title, action) in [
                ("Start VanishCam", #selector(start)),
                ("Stop VanishCam", #selector(stop)),
                ("Show myself", #selector(showMyself)),
                ("Reset background", #selector(resetBackground))
            ] {
                let button = NSButton(title: title, target: self, action: action)
                button.bezelStyle = .rounded
                controls.addArrangedSubview(button)
                if action == #selector(start) { startButton = button }
                if action == #selector(stop) { stopButton = button }
                if action == #selector(showMyself) { showMyselfButton = button }
                if action == #selector(resetBackground) { resetButton = button }
            }
            stack.addArrangedSubview(controls)
            if packaged {
                let effects = NSStackView()
                effects.spacing = 12
                for (title, key) in [("Dissolve", 49), ("Naruto", 50), ("Goku", 51)] {
                    let button = NSButton(title: title, target: self, action: #selector(triggerEffect(_:)))
                    button.tag = key
                    effects.addArrangedSubview(button)
                    effectButtons.append(button)
                }
                stack.addArrangedSubview(effects)
            }
            let content = window.contentView!
            content.addSubview(stack)
            NSLayoutConstraint.activate([
                stack.leadingAnchor.constraint(equalTo: content.leadingAnchor),
                stack.trailingAnchor.constraint(equalTo: content.trailingAnchor),
                stack.topAnchor.constraint(equalTo: content.topAnchor),
                stack.bottomAnchor.constraint(lessThanOrEqualTo: content.bottomAnchor)
            ])
            window.center()
            controlsWindow = window
            if packaged { refreshCameras() }
        }
        updateControls()
        hidePreviewItem?.isEnabled = show
        if show {
            controlsWindow?.makeKeyAndOrderFront(nil)
            NSApplication.shared.activate(ignoringOtherApps: true)
            if !CommandLine.arguments.contains("--ui-self-test") {
                UserDefaults.standard.set(true, forKey: "ShowControlsOnLaunch")
            }
        }
    }

    private func updateControls() {
        let running = process != nil
        let available = !packaged || (selectedCamera != nil && !selectedProfile.mode.isEmpty)
        startButton?.isEnabled = !running && available
        startItem?.isEnabled = !running && available
        cameraPicker?.isEnabled = !running
        modePicker?.isEnabled = !running
        refreshButton?.isEnabled = !running
        stopButton?.isEnabled = running && !stopping
        stopItem?.isEnabled = running && !stopping
        showMyselfItem?.isEnabled = running && !stopping
        showMyselfButton?.isEnabled = running && !stopping
        let effects = !packaged || effectsToggle?.state == .on
        effectsToggle?.isEnabled = !stopping
        gesturesToggle?.isEnabled = effects && !stopping
        resetButton?.isEnabled = running && !stopping && effects
        resetMenuItem?.isEnabled = running && !stopping && effects
        effectButtons.forEach { $0.isEnabled = running && !stopping && effects && backgroundReady }
        effectsMenuItem?.state = effectsToggle?.state ?? .off
        effectsMenuItem?.isEnabled = !stopping
        gesturesMenuItem?.state = gesturesToggle?.state ?? .off
        gesturesMenuItem?.isEnabled = effects && !stopping
        effectMenuItems.forEach { $0.isEnabled = running && !stopping && effects && backgroundReady }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        openControls()
        return true
    }

    private var logURL: URL {
        packaged ? stateDirectory.appendingPathComponent("launch.log") : root.appendingPathComponent("build/vanishcam-launch.log")
    }

    @objc private func start() {
        guard process == nil else { return }
        do {
            try FileManager.default.createDirectory(at: stateDirectory, withIntermediateDirectories: true)
            try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: stateDirectory.path)
            try Data().write(to: logURL)
            let handle = try FileHandle(forWritingTo: logURL)
            logHandle = handle
            let child = Process()
            if packaged {
                if selectedCamera == nil { refreshCameras() }
                guard let camera = selectedCamera else {
                    throw NSError(domain: "VanishCam", code: 3, userInfo: [NSLocalizedDescriptionKey: "Selected camera unavailable. Refresh cameras and choose another."])
                }
                let mode = selectedProfile.mode.components(separatedBy: " @ ")
                let outputSize = mode.first?.components(separatedBy: "x") ?? []
                guard mode.count == 2, outputSize.count == 2, supportedModes(camera).contains(selectedProfile.mode) else {
                    throw NSError(domain: "VanishCam", code: 4, userInfo: [NSLocalizedDescriptionKey: "Selected capture mode is unavailable. Refresh cameras and choose a supported mode."])
                }
                try savePreferences()
                effectsToggle?.state = .off
                gesturesToggle?.state = .off
                backgroundReady = false
                try saveCallControls()
                for name in ["reset-background", "show-myself"] {
                    let request = stateDirectory.appendingPathComponent(name)
                    if FileManager.default.fileExists(atPath: request.path) {
                        try FileManager.default.removeItem(at: request)
                    }
                }
                let keyRequest = stateDirectory.appendingPathComponent("key-request")
                if FileManager.default.fileExists(atPath: keyRequest.path) {
                    try FileManager.default.removeItem(at: keyRequest)
                }
                child.executableURL = engineURL
                child.arguments = [
                    "--camera-name", camera.localizedName, "--no-mirror", "--virtual-camera",
                    "--capture-size", mode[0], "--fps", mode[1],
                    "--width", outputSize[0], "--height", String((Int(outputSize[0]) ?? 1920) * 9 / 16 / 2 * 2),
                    "--virtual-backend", "obs", "--virtual-device", "OBS Virtual Camera",
                    "--background-file", backgroundURL.path,
                    "--framing-file", profileDirectory.appendingPathComponent("framing.json").path,
                    "--manual-calibration",
                    "--controls-file", stateDirectory.appendingPathComponent("call-controls.json").path,
                    "--reset-background-request", stateDirectory.appendingPathComponent("reset-background").path,
                    "--show-myself-request", stateDirectory.appendingPathComponent("show-myself").path,
                    "--key-request", keyRequest.path, "--preview-stream"
                ]
                child.currentDirectoryURL = stateDirectory
                var environment = ProcessInfo.processInfo.environment
                environment["PYTHONUNBUFFERED"] = "1"
                environment["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
                child.environment = environment
            } else {
                child.executableURL = URL(fileURLWithPath: "/bin/bash")
                child.arguments = [root.appendingPathComponent("VanishCam.command").path]
                child.currentDirectoryURL = root
            }
            child.standardInput = FileHandle.nullDevice
            let pipe = packaged ? Pipe() : nil
            if let pipe = pipe {
                child.standardOutput = pipe
            } else {
                child.standardOutput = handle
            }
            child.standardError = handle
            child.terminationHandler = { [weak self] finished in
                DispatchQueue.main.async {
                    self?.finished(status: finished.terminationStatus)
                }
            }
            try child.run()
            process = child
            previewPipe = pipe
            if let pipe = pipe {
                readPreview(pipe.fileHandleForReading, child: child)
            }
            stopping = false
            startItem.isEnabled = false
            stopItem.isEnabled = true
            showMyselfItem.isEnabled = true
            updateIcon(running: true)
            updateControls()
            if packaged { effectButtons.forEach { $0.isEnabled = false } }
            statusLabel?.stringValue = "Starting selected camera and effects…"
            statusItem.button?.toolTip = "Camera on; saved background reused if available"
        } catch {
            statusLabel?.stringValue = "Could not start"
            closeLog()
            showError("Could not start VanishCam", detail: error.localizedDescription)
        }
    }

    @objc private func stop() {
        guard let child = process, child.isRunning else { return }
        stopping = true
        stopItem.isEnabled = false
        statusItem.button?.toolTip = "VanishCam is stopping"
        updateControls()
        statusLabel?.stringValue = "Stopping…"
        if packaged {
            do {
                try sendKey("q")
            } catch {
                showError("Could not send Stop", detail: error.localizedDescription)
                child.terminate()
            }
            let timeout = DispatchWorkItem { [weak self, weak child] in
                guard let self = self, let child = child, child.isRunning else { return }
                self.statusLabel?.stringValue = "Stopping video engine…"
                child.terminate()
            }
            stopTimeout = timeout
            DispatchQueue.main.asyncAfter(deadline: .now() + 20, execute: timeout)
        } else {
            child.interrupt()
        }
    }

    private func sendKey(_ key: String) throws {
        try Data(key.utf8).write(to: stateDirectory.appendingPathComponent("key-request"), options: .atomic)
    }

    @objc private func triggerEffect(_ sender: NSButton) {
        do {
            try sendKey(String(UnicodeScalar(sender.tag)!))
        } catch {
            showError("Could not trigger effect", detail: error.localizedDescription)
        }
    }

    private func readPreview(_ handle: FileHandle, child: Process) {
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            func readExactly(_ count: Int) throws -> Data? {
                var result = Data()
                while result.count < count {
                    guard let chunk = try handle.read(upToCount: count - result.count), !chunk.isEmpty else {
                        if result.isEmpty { return nil }
                        throw NSError(domain: "VanishCam", code: 1, userInfo: [NSLocalizedDescriptionKey: "Incomplete preview packet"])
                    }
                    result.append(chunk)
                }
                return result
            }
            do {
                while let header = try readExactly(4) {
                    let size = header.reduce(0) { ($0 << 8) | Int($1) }
                    guard size > 0 && size <= 8_000_000,
                          let payload = try readExactly(size),
                          let separator = payload.firstIndex(of: 0),
                          let status = String(data: payload[..<separator], encoding: .utf8),
                          let image = NSImage(data: payload[(separator + 1)...]) else {
                        throw NSError(domain: "VanishCam", code: 2, userInfo: [NSLocalizedDescriptionKey: "Invalid preview packet"])
                    }
                    DispatchQueue.main.async {
                        guard let self = self, self.process === child, !self.stopping else { return }
                        self.previewView?.image = image
                        self.statusLabel?.stringValue = "\(status) · OBS Virtual Camera"
                        let effectsReady = !status.contains("set framing") && !status.hasPrefix("Step out:")
                        self.backgroundReady = effectsReady && !status.hasPrefix("Normal video")
                        self.updateControls()
                    }
                }
            } catch {
                DispatchQueue.main.async {
                    guard let self = self, self.process === child, !self.stopping else { return }
                    self.showError("Preview connection failed", detail: error.localizedDescription)
                    self.stop()
                }
            }
        }
    }

    @objc private func resetBackground() {
        guard process?.isRunning == true, !packaged || effectsToggle?.state == .on else { return }
        let directory = stateDirectory
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            if process?.isRunning == true {
                try Data().write(to: directory.appendingPathComponent("reset-background"), options: .atomic)
                statusLabel?.stringValue = "Background capture requested — step out for four seconds"
            } else {
                let background = packaged ? backgroundURL : directory.appendingPathComponent("background.png")
                if FileManager.default.fileExists(atPath: background.path) {
                    try FileManager.default.removeItem(at: background)
                }
                let alert = NSAlert()
                alert.messageText = "Background reset"
                alert.informativeText = "Next time you start VanishCam, step out of frame for four seconds to capture and save a new background."
                alert.runModal()
            }
        } catch {
            showError("Could not reset background", detail: error.localizedDescription)
        }
    }

    @objc private func showMyself() {
        guard process?.isRunning == true else { return }
        do {
            let directory = stateDirectory
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            try Data().write(to: directory.appendingPathComponent("show-myself"), options: .atomic)
            statusLabel?.stringValue = "Restoring live camera…"
        } catch {
            showError("Could not restore live video", detail: error.localizedDescription)
        }
    }

    private func finished(status: Int32) {
        let expectedStop = stopping
        process = nil
        stopTimeout?.cancel()
        stopTimeout = nil
        previewPipe = nil
        stopping = false
        closeLog()
        startItem.isEnabled = true
        stopItem.isEnabled = false
        showMyselfItem.isEnabled = false
        updateIcon(running: false)
        statusItem.button?.toolTip = "VanishCam is off"
        if packaged { refreshCameras() }
        updateControls()
        previewView?.image = nil
        statusLabel?.stringValue = status == 0 || expectedStop ? "Camera stopped" : "Video engine failed — open launch log"
        if quitting {
            NSApplication.shared.reply(toApplicationShouldTerminate: true)
        } else if status != 0 && !expectedStop {
            showError("VanishCam stopped with an error", detail: "Check that the selected camera is connected and not held by another app. The MacBook lid must be open for its built-in camera. Check that the OBS camera extension is enabled. Open the launch log for details.")
        }
    }

    private func closeLog() {
        guard let handle = logHandle else { return }
        logHandle = nil
        do {
            try handle.close()
        } catch {
            showError("Could not close launch log", detail: error.localizedDescription)
        }
    }

    private func updateIcon(running: Bool) {
        statusItem.button?.image = nil
        statusItem.button?.title = "VC"
        statusItem.button?.setAccessibilityLabel("VanishCam")
    }

    @objc private func showHelp() {
        let alert = NSAlert()
        alert.messageText = "Using VanishCam"
        alert.informativeText = """
        Select Logitech or the Mac camera directly, or Camo Camera to use Camo's adjustments. Keep Camo Studio running only when using Camo Camera. Leave OBS's own virtual-camera stream stopped.

        Set capture resolution/FPS while stopped. Zoom and position can be adjusted live. Settings and backgrounds are separate for each camera. After framing, click Reset background and step out for four seconds. In Teams, select OBS Virtual Camera.

        Every start uses Normal video: OBS stays live, effects and gestures are off. Enable effects to use effect buttons. Hand gestures are a separate opt-in control. Turning effects off immediately restores normal video, including during capture.

        Gestures need a stable 0.9-second hold. Release to a neutral pose for 0.4 seconds before triggering again. Goku requires your face to be visible. Buttons work immediately.

        Reset background captures a replacement only when clicked while effects are enabled. Missing or invalid backgrounds never trigger automatic capture.

        Show myself immediately restores live video without keyboard focus or a Goku cooldown. It does not replace the saved background.

        Use gestures or the effect buttons in the packaged app. In the command-line preview:
        1: dissolve (or hold a peace sign)
        2: Naruto (or bring palms together)
        3: Goku (or two fingers at your temple)
        R: return; Space: recalibrate; Q/Esc: stop

        Stop releases the camera so you can switch cameras or use it directly in Teams. If your saved camera is absent, refresh the list and explicitly select another.
        """
        alert.runModal()
    }

    @objc private func showLog() {
        if !NSWorkspace.shared.open(logURL) {
            showError("No launch log yet", detail: "Start VanishCam to create the log.")
        }
    }

    private func showError(_ message: String, detail: String) {
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = message
        alert.informativeText = detail
        alert.runModal()
    }

    @objc private func quitApp() {
        NSApplication.shared.terminate(nil)
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard process?.isRunning == true else { return .terminateNow }
        quitting = true
        stop()
        return .terminateLater
    }
}
