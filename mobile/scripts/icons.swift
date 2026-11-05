import AppKit
import Foundation
let args = CommandLine.arguments
let base = URL(fileURLWithPath: args.count > 1 ? args[1] : FileManager.default.currentDirectoryPath)
guard let source = NSImage(contentsOf: base.appendingPathComponent("resources/brand-source.png")) else { fatalError("Missing original company mark") }
func render(_ size: Int, _ fraction: CGFloat, _ transparent: Bool, _ destination: String) throws {
    let rep = NSBitmapImageRep(bitmapDataPlanes:nil, pixelsWide:size, pixelsHigh:size, bitsPerSample:8, samplesPerPixel:transparent ? 4 : 3, hasAlpha:transparent, isPlanar:false, colorSpaceName:.deviceRGB, bytesPerRow:0, bitsPerPixel:0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep:rep)
    if !transparent { NSColor(red:247/255,green:246/255,blue:241/255,alpha:1).setFill(); NSBezierPath(rect:NSRect(x:0,y:0,width:size,height:size)).fill() }
    let side = CGFloat(size) * fraction, offset = (CGFloat(size)-side)/2
    source.draw(in:NSRect(x:offset,y:offset,width:side,height:side),from:.zero,operation:.sourceOver,fraction:1)
    NSGraphicsContext.restoreGraphicsState()
    let url=base.appendingPathComponent(destination)
    try FileManager.default.createDirectory(at:url.deletingLastPathComponent(),withIntermediateDirectories:true)
    try rep.representation(using:.png,properties:[:])!.write(to:url)
}
// Preserve the original company mark; only size and safe padding are adapted for launcher assets.
try render(1024,0.70,false,"resources/app-icon.png")
try render(1024,0.70,false,"ios/App/App/Assets.xcassets/AppIcon.appiconset/AppIcon-512@2x.png")
for (density,size) in [("mdpi",48),("hdpi",72),("xhdpi",96),("xxhdpi",144),("xxxhdpi",192)] {
    try render(size,0.70,false,"android/app/src/main/res/mipmap-\(density)/ic_launcher.png")
    try render(size,0.70,false,"android/app/src/main/res/mipmap-\(density)/ic_launcher_round.png")
    try render(Int(Double(size)*2.25),0.52,true,"android/app/src/main/res/mipmap-\(density)/ic_launcher_foreground.png")
}
for name in ["splash-2732x2732.png","splash-2732x2732-1.png","splash-2732x2732-2.png"] {
    try render(2732,0.12,false,"ios/App/App/Assets.xcassets/Splash.imageset/\(name)")
}
print("Generated launcher and launch assets from the original company mark.")
