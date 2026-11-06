import Foundation
import Observation

/// Owns the engine process: starts it, watches it, restarts it if it crashes, and stops it when
/// Vox quits.
///
/// The engine is always started directly with `Process()`. That makes Vox.app the *responsible
/// process* for macOS privacy permissions, so the microphone and Accessibility grants the user
/// gives "Vox" apply to the Python engine too. Launching it any other way (launchd, `open`, a
/// Terminal) would attribute the permissions to something else and the mic would record silence.
@MainActor
@Observable
final class EngineSupervisor {
    enum State: Equatable {
        case notInstalled
        case stopped
        case starting
        /// `owned` is false when the engine was already running when Vox opened (e.g. started from
        /// a terminal) or relaunched itself (the voice "restart Vox" path). Vox watches it either way.
        case running(owned: Bool)
        case failed(String)
    }

    private(set) var state: State = .stopped
    private(set) var status: EngineStatus?
    private(set) var location = EngineLocation.detect()
    /// When the current state began (drives "Starting… 12s" and the crash backoff).
    private(set) var since = Date()

    let api = APIClient()
    private var process: Process?
    private var stopping = false
    private var pollTask: Task<Void, Never>?
    private var recentCrashes: [Date] = []
    /// Set while engineExited is deciding what happened. The termination handler and the health
    /// poll can both notice the same exit, so without this one crash ran two recoveries.
    private var recovering = false
    /// True between start() deciding to launch and the state settling, so a second Start press
    /// (or onboarding re-entering the Engine step) can't spawn a second engine on the same mic.
    private var starting = false
    /// Consecutive failed health checks. One timeout isn't a dead engine.
    private var failedPolls = 0

    var isRunning: Bool { if case .running = state { return true }; return false }
    var isStarting: Bool { starting || state == .starting }

    init() {
        if !location.isReady { state = .notInstalled }
    }

    func refreshLocation() {
        location = EngineLocation.detect()
        if !location.isReady { set(.notInstalled) } else if state == .notInstalled { set(.stopped) }
    }

    // MARK: Lifecycle

    /// Attach to a running engine if there is one, otherwise start ours. Idempotent: does nothing
    /// while an engine is starting or running.
    func start() {
        startPolling()
        switch state {
        case .starting, .running: return
        default: break
        }
        guard !starting else { return }
        starting = true
        Task {
            defer { starting = false }
            if (try? await api.status()) != nil { set(.running(owned: false)); return }
            launch()
        }
    }

    func stop() async {
        stopping = true
        defer { stopping = false }
        if let p = process, p.isRunning {
            p.terminate()
            for _ in 0..<30 where p.isRunning { try? await Task.sleep(for: .milliseconds(100)) }
            if p.isRunning { kill(p.processIdentifier, SIGKILL) }
        } else if let pid = status?.pid {
            // Not our child (it relaunched itself or was started elsewhere), so signal it by PID.
            kill(pid_t(pid), SIGTERM)
            for _ in 0..<30 where (try? await api.status()) != nil { try? await Task.sleep(for: .milliseconds(100)) }
        }
        process = nil
        status = nil
        set(location.isReady ? .stopped : .notInstalled)
    }

    func restart() {
        Task {
            await stop()
            launch()
        }
    }

    /// Synchronous best-effort stop for app termination. Covers an engine Vox didn't spawn too
    /// (after a voice "restart Vox" the engine is a new, detached process), or quitting Vox would
    /// leave the microphone live.
    func stopForQuit() {
        stopping = true
        if let p = process, p.isRunning {
            p.terminate()
        } else if let pid = status?.pid, pid > 1 {
            kill(pid_t(pid), SIGTERM)
        }
    }

    private func launch() {
        guard location.isReady else { set(.notInstalled); return }
        let p = Process()
        p.executableURL = location.python
        p.arguments = ["-m", "vox"]
        p.currentDirectoryURL = location.kind == .checkout ? location.engineDir : location.resolvedDataDir
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = EngineLocation.childPATH
        env["PYTHONUNBUFFERED"] = "1"
        env["VOX_APP"] = "1"   // the engine can tell it's supervised (e.g. don't open browser tabs)
        if let data = location.dataDir {
            try? FileManager.default.createDirectory(at: data, withIntermediateDirectories: true)
            env["VOX_DATA_DIR"] = data.path
        }
        p.environment = env
        if let console = Self.consoleLog() {
            p.standardOutput = console
            p.standardError = console
        }
        p.terminationHandler = { [weak self] proc in
            let code = proc.terminationStatus
            Task { @MainActor in
                // Only the process we're tracking counts; an older one exiting late must not
                // clear the live one.
                guard let self, self.process === proc else { return }
                self.engineExited(code: Int32?(code))
            }
        }
        do {
            try p.run()
            process = p
            set(.starting)
        } catch {
            set(.failed("Couldn't start the engine: \(error.localizedDescription)"))
        }
    }

    /// `code` is the exit status of a process we spawned, or nil when the health check noticed an
    /// engine we didn't spawn has gone.
    private func engineExited(code: Int32?) {
        process = nil
        if stopping || recovering { return }
        recovering = true
        set(.starting)
        // The engine relaunches itself on "restart Vox" and on an unrecoverable mic error. Give the
        // replacement a moment to come up before deciding anything.
        Task {
            defer { recovering = false }
            for _ in 0..<40 {
                if (try? await api.status()) != nil { set(.running(owned: false)); return }
                try? await Task.sleep(for: .milliseconds(250))
            }
            // A clean exit (saying "quit Vox" exits 0) or an engine we didn't start going away is the
            // user's decision, not a crash: bringing it back would make "quit Vox" not stick.
            guard let code, code != 0 else { set(.stopped); return }
            recentCrashes = recentCrashes.filter { $0.timeIntervalSinceNow > -120 } + [Date()]
            if recentCrashes.count >= 3 {
                set(.failed("Vox's engine keeps stopping (exit code \(code)). Settings → Advanced → Open Console Output shows why."))
            } else {
                launch()
            }
        }
    }

    // MARK: Health

    private func startPolling() {
        guard pollTask == nil else { return }
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.poll()
                try? await Task.sleep(for: .seconds(1.5))
            }
        }
    }

    /// Re-read status now (after an action that changes it), instead of waiting for the next poll.
    func refreshStatus() async {
        if let s = try? await api.status() { status = s }
    }

    private func poll() async {
        let s = try? await api.status()
        failedPolls = s == nil ? failedPolls + 1 : 0
        // Keep the last good status through a single slow or failed check: swapping every page for
        // "Starting…" on one timeout closed open sheets and lost their drafts.
        if let s, s != status { status = s }
        if s == nil && failedPolls >= 2 { status = nil }
        switch state {
        case .starting where s != nil && !recovering:
            set(.running(owned: process != nil))
        case .running where s == nil && failedPolls >= 2 && process == nil && !stopping:
            engineExited(code: nil)
        case .stopped where s != nil, .notInstalled where s != nil, .failed where s != nil:
            set(.running(owned: false))
        default:
            break
        }
    }

    /// Snapshot/preview only.
    func previewRunning(_ s: EngineStatus) {
        status = s
        state = .running(owned: true)
    }

    private func set(_ new: State) {
        if new != state { state = new; since = Date() }
    }

    /// Engine stdout/stderr go to ~/Library/Logs/Vox/engine-console.log (truncated on each start).
    private static func consoleLog() -> FileHandle? {
        let dir = FileManager.default.homeDirectoryForCurrentUser.appending(path: "Library/Logs/Vox")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let file = dir.appending(path: "engine-console.log")
        FileManager.default.createFile(atPath: file.path, contents: nil)
        return try? FileHandle(forWritingTo: file)
    }

    static var consoleLogURL: URL {
        FileManager.default.homeDirectoryForCurrentUser.appending(path: "Library/Logs/Vox/engine-console.log")
    }
}
