import AppKit

/// Hold-to-talk (ideas #69.1): hold Right Option, speak, let go. No wake word, and letting go ends
/// the turn immediately instead of waiting for silence, so a thinking pause can't cut you off.
///
/// To avoid hijacking Option shortcuts (⌥E, ⌥-click…), talking only starts once the key has been
/// held alone for a moment, and pressing any other key cancels it. Watching keys in other apps
/// needs the Accessibility permission Vox already asks for.
@MainActor
final class HoldToTalk {
    static let shared = HoldToTalk()

    var api = APIClient()
    private var monitors: [Any] = []
    private var pending: DispatchWorkItem?
    private var talking = false
    /// Press and release go out strictly in order: two independent requests can land swapped,
    /// leaving the engine thinking the key is still held.
    private var sendChain: Task<Void, Never>?
    private static let rightOption: UInt16 = 61
    private static let holdDelay = 0.2

    static var enabled: Bool {
        get { UserDefaults.standard.object(forKey: "holdToTalk") as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: "holdToTalk"); newValue ? shared.start() : shared.stop() }
    }

    func start() {
        guard monitors.isEmpty, Self.enabled else { return }
        let flags: (NSEvent) -> Void = { [weak self] e in Task { @MainActor in self?.flagsChanged(e) } }
        let keys: (NSEvent) -> Void = { [weak self] _ in Task { @MainActor in self?.otherKey() } }
        if let m = NSEvent.addGlobalMonitorForEvents(matching: .flagsChanged, handler: flags) { monitors.append(m) }
        if let m = NSEvent.addGlobalMonitorForEvents(matching: .keyDown, handler: keys) { monitors.append(m) }
        if let m = NSEvent.addLocalMonitorForEvents(matching: .flagsChanged, handler: { flags($0); return $0 }) { monitors.append(m) }
        if let m = NSEvent.addLocalMonitorForEvents(matching: .keyDown, handler: { keys($0); return $0 }) { monitors.append(m) }
    }

    func stop() {
        monitors.forEach { NSEvent.removeMonitor($0) }
        monitors.removeAll()
        release()
    }

    private func flagsChanged(_ e: NSEvent) {
        guard e.keyCode == Self.rightOption else { return }
        if e.modifierFlags.contains(.option) {
            let work = DispatchWorkItem { [weak self] in Task { @MainActor in self?.begin() } }
            pending = work
            DispatchQueue.main.asyncAfter(deadline: .now() + Self.holdDelay, execute: work)
        } else {
            release()
        }
    }

    /// Another key while Option is down means it's a shortcut, not a request to talk.
    private func otherKey() {
        pending?.cancel(); pending = nil
        if talking { release() }
    }

    private func begin() {
        pending = nil
        talking = true
        NSSound(named: "Tink")?.play()
        send(true)
    }

    private func release() {
        pending?.cancel(); pending = nil
        guard talking else { return }
        talking = false
        NSSound(named: "Pop")?.play()
        send(false)
    }

    private func send(_ held: Bool) {
        let previous = sendChain
        let api = self.api
        sendChain = Task {
            await previous?.value
            try? await api.post("ptt", ["held": .bool(held)])
        }
    }

    /// App quitting mid-hold: release synchronously-ish so the engine isn't left listening.
    func releaseForQuit() {
        guard talking else { return }
        talking = false
        var req = URLRequest(url: URL(string: "http://127.0.0.1:\(api.port)/api/ptt")!)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = Data(#"{"held":false}"#.utf8)
        req.timeoutInterval = 1
        let done = DispatchSemaphore(value: 0)
        URLSession.shared.dataTask(with: req) { _, _, _ in done.signal() }.resume()
        _ = done.wait(timeout: .now() + 1)
    }
}
