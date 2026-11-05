import AppKit

let directory = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
for size in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        let pixels = size * scale
        let image = NSImage(size: NSSize(width: pixels, height: pixels))
        image.lockFocus()
        NSColor.systemTeal.setFill()
        NSBezierPath(roundedRect: NSRect(x: 0, y: 0, width: pixels, height: pixels),
                     xRadius: CGFloat(pixels) * 0.2, yRadius: CGFloat(pixels) * 0.2).fill()
        NSColor.white.setFill()
        NSBezierPath(roundedRect: NSRect(x: CGFloat(pixels) * 0.18, y: CGFloat(pixels) * 0.3,
                                        width: CGFloat(pixels) * 0.43, height: CGFloat(pixels) * 0.4),
                     xRadius: CGFloat(pixels) * 0.06, yRadius: CGFloat(pixels) * 0.06).fill()
        let lens = NSBezierPath()
        lens.move(to: NSPoint(x: CGFloat(pixels) * 0.65, y: CGFloat(pixels) * 0.4))
        lens.line(to: NSPoint(x: CGFloat(pixels) * 0.82, y: CGFloat(pixels) * 0.3))
        lens.line(to: NSPoint(x: CGFloat(pixels) * 0.82, y: CGFloat(pixels) * 0.7))
        lens.line(to: NSPoint(x: CGFloat(pixels) * 0.65, y: CGFloat(pixels) * 0.6))
        lens.close()
        lens.fill()
        image.unlockFocus()
        guard let tiff = image.tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiff),
              let png = bitmap.representation(using: .png, properties: [:]) else {
            fatalError("Cannot render VanishCam app icon.")
        }
        let suffix = scale == 2 ? "@2x" : ""
        try png.write(to: directory.appendingPathComponent("icon_\(size)x\(size)\(suffix).png"))
    }
}
