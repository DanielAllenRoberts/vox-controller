// Draws Vox's app icon at every size macOS wants and writes an .iconset folder.
//   swift app/scripts/make-icon.swift <out.iconset> && iconutil -c icns <out.iconset>
// A rounded square on a deep blue-violet gradient with a white voice waveform, inset to the
// standard macOS icon grid (the shape fills ~80% of the canvas, leaving room for the shadow).
import AppKit

let out = URL(fileURLWithPath: CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "AppIcon.iconset")
try? FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)

func draw(_ px: Int) -> Data {
    let s = CGFloat(px)
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px, bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                               colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    let ctx = NSGraphicsContext.current!.cgContext

    let inset = s * 0.1, side = s - inset * 2
    let rect = CGRect(x: inset, y: inset * 1.15, width: side, height: side)
    let shape = CGPath(roundedRect: rect, cornerWidth: side * 0.225, cornerHeight: side * 0.225, transform: nil)

    // Soft drop shadow.
    ctx.saveGState()
    ctx.setShadow(offset: CGSize(width: 0, height: -s * 0.012), blur: s * 0.03,
                  color: NSColor.black.withAlphaComponent(0.35).cgColor)
    ctx.addPath(shape); ctx.setFillColor(NSColor.black.cgColor); ctx.fillPath()
    ctx.restoreGState()

    // Gradient body.
    ctx.saveGState()
    ctx.addPath(shape); ctx.clip()
    let colors = [NSColor(srgbRed: 0.36, green: 0.30, blue: 0.98, alpha: 1).cgColor,
                  NSColor(srgbRed: 0.10, green: 0.55, blue: 1.00, alpha: 1).cgColor] as CFArray
    let grad = CGGradient(colorsSpace: CGColorSpace(name: CGColorSpace.sRGB), colors: colors, locations: [0, 1])!
    ctx.drawLinearGradient(grad, start: CGPoint(x: rect.minX, y: rect.maxY), end: CGPoint(x: rect.maxX, y: rect.minY), options: [])
    // Top sheen.
    let sheen = CGGradient(colorsSpace: CGColorSpace(name: CGColorSpace.sRGB),
                           colors: [NSColor.white.withAlphaComponent(0.22).cgColor, NSColor.white.withAlphaComponent(0).cgColor] as CFArray,
                           locations: [0, 1])!
    ctx.drawLinearGradient(sheen, start: CGPoint(x: 0, y: rect.maxY), end: CGPoint(x: 0, y: rect.midY), options: [])
    ctx.restoreGState()

    // Waveform: seven rounded bars, tallest in the middle.
    let heights: [CGFloat] = [0.20, 0.38, 0.56, 0.72, 0.56, 0.38, 0.20]
    let barW = side * 0.07, gap = side * 0.045
    let total = CGFloat(heights.count) * barW + CGFloat(heights.count - 1) * gap
    var x = rect.midX - total / 2
    ctx.setFillColor(NSColor.white.cgColor)
    for h in heights {
        let bh = side * h
        let bar = CGRect(x: x, y: rect.midY - bh / 2, width: barW, height: bh)
        ctx.addPath(CGPath(roundedRect: bar, cornerWidth: barW / 2, cornerHeight: barW / 2, transform: nil))
        ctx.fillPath()
        x += barW + gap
    }

    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}

for base in [16, 32, 128, 256, 512] {
    try! draw(base).write(to: out.appending(path: "icon_\(base)x\(base).png"))
    try! draw(base * 2).write(to: out.appending(path: "icon_\(base)x\(base)@2x.png"))
}
print("wrote \(out.path)")
