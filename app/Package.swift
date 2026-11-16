// swift-tools-version:5.10
// Vox.app: the native macOS shell for the Vox engine. Builds with the Command Line Tools alone
// (no Xcode): `app/build.sh` compiles this package and assembles Vox.app around the binary.
import PackageDescription

let package = Package(
    name: "Vox",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "Vox",
            path: "Sources/Vox",
            swiftSettings: [.unsafeFlags(["-parse-as-library"])]
        ),
    ]
)
