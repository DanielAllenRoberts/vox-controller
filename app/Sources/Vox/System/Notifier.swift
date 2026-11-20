import Foundation
import UserNotifications

/// `Vox --notify <title> <body>`: posts one macOS notification as Vox, then exits.
///
/// The engine and each agent's MCP server are Python processes with no bundle of their own, so
/// they run this binary to post a real notification (Vox's name and icon, Notification Center,
/// Focus modes) instead of drawing their own card. Exit code 0 means it was posted; anything else
/// (3 = notifications are off for Vox in System Settings) and the caller falls back to the card
/// (`vox.bubble`).
enum Notifier {
    /// Asked once by the app at launch, so macOS's "allow notifications?" prompt belongs to the
    /// app that stays open, not to a helper that exits.
    static func askPermission() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert]) { _, _ in }
    }

    static func run(title: String, body: String) -> Never {
        let center = UNUserNotificationCenter.current()
        center.requestAuthorization(options: [.alert]) { granted, error in
            guard granted else {
                FileHandle.standardError.write(Data("notify: \(error?.localizedDescription ?? "not allowed")\n".utf8))
                exit(3)
            }
            let content = UNMutableNotificationContent()
            content.title = title
            content.body = body
            let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
            center.add(request) { error in exit(error == nil ? 0 : 1) }
        }
        RunLoop.main.run(until: Date().addingTimeInterval(60))   // waiting on the permission prompt
        exit(2)
    }
}
