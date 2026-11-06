import AppKit
import SwiftUI

// Small pieces shared by the pages.

/// The centred spinner a page shows before its first load lands.
struct PageLoading: View {
    var body: some View {
        ProgressView().controlSize(.small).frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

extension View {
    /// The small grey look of `SectionLabel`, for section headers inside a Form or List, so every
    /// page's headers match whatever layout it uses.
    func pageSectionHeader() -> some View {
        font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
    }
}

/// A trash button that only appears while its row is hovered, so lists stay calm.
struct HoverDeleteButton: View {
    var visible: Bool
    var help: String
    var action: () -> Void

    var body: some View {
        Button(help, systemImage: "trash", role: .destructive, action: action)
            .labelStyle(.iconOnly)
            .buttonStyle(.borderless)
            .foregroundStyle(.secondary)
            .opacity(visible ? 1 : 0)
            .help(help)
            .accessibilityHidden(!visible)
    }
}

/// The icon of an installed app, looked up by name. Cached; nil when the app isn't found.
@MainActor
enum AppIcons {
    private static var cache: [String: NSImage?] = [:]

    static func icon(for name: String) -> NSImage? {
        if let hit = cache[name] { return hit }
        let dirs = ["/Applications", "/System/Applications", "/Applications/Utilities",
                    "/System/Applications/Utilities", NSHomeDirectory() + "/Applications"]
        let path = dirs.map { "\($0)/\(name).app" }.first { FileManager.default.fileExists(atPath: $0) }
        let image = path.map { NSWorkspace.shared.icon(forFile: $0) }
        cache[name] = image
        return image
    }
}
