import AppKit
import SwiftUI

// Small pieces shared by the Teach Vox pages (Personality, Commands, Vocabulary, Rules).

/// A failed request, shown in place at the top of a page. Dismissable; never a modal.
struct InlineError: View {
    var message: String
    var onDismiss: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange)
            Text(message).lineLimit(3)
            Spacer(minLength: 8)
            Button("Dismiss", systemImage: "xmark", action: onDismiss)
                .labelStyle(.iconOnly).buttonStyle(.borderless).foregroundStyle(.secondary)
        }
        .font(.callout)
        .padding(.horizontal, 14).padding(.vertical, 10)
        .background(Color.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .padding(.horizontal, Metrics.page).padding(.top, Metrics.tight)
        .transition(.move(edge: .top).combined(with: .opacity))
    }
}

extension View {
    /// Pins an `InlineError` above the page content while `error` is set.
    func inlineError(_ error: Binding<String?>) -> some View {
        safeAreaInset(edge: .top, spacing: 0) {
            if let message = error.wrappedValue {
                InlineError(message: message) { withAnimation(.smooth) { error.wrappedValue = nil } }
            }
        }
        .animation(.smooth, value: error.wrappedValue)
    }
}

/// The centred spinner a page shows before its first load lands.
struct PageLoading: View {
    var body: some View {
        ProgressView().controlSize(.small).frame(maxWidth: .infinity, maxHeight: .infinity)
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
