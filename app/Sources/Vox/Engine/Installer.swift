import Foundation
import Observation

/// First-run engine install: unpack the bundled engine source, then let the bundled `uv` install a
/// private Python 3.12 and the locked dependencies into ~/Library/Application Support/Vox.
/// Nothing touches the system Python or Homebrew (`--python-preference only-managed`), and a re-run
/// is safe: `uv sync` is idempotent, so "Retry" just runs the same steps again.
@MainActor
@Observable
final class Installer {
    enum Phase: Equatable { case idle, running, done, failed(String) }

    private(set) var phase: Phase = .idle
    private(set) var step = ""
    private(set) var lines: [String] = []
    /// 0…1 for the coarse stages; uv doesn't report byte progress.
    private(set) var progress: Double = 0

    func install(into loc: EngineLocation) async {
        phase = .running
        lines = []
        do {
            try await run(loc)
            phase = .done
            progress = 1
            step = "Ready"
        } catch {
            phase = .failed(error.localizedDescription)
        }
    }

    private func run(_ loc: EngineLocation) async throws {
        let fm = FileManager.default
        guard let uv = EngineLocation.bundledUV ?? Self.systemUV() else {
            throw Failure("This copy of Vox is missing its installer (uv). Download Vox again.")
        }
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = EngineLocation.childPATH
        if loc.kind == .installed {
            step = "Unpacking Vox"; progress = 0.05
            guard let src = EngineLocation.bundledEngine else {
                throw Failure("This copy of Vox doesn't include the engine. Download Vox again.")
            }
            try fm.createDirectory(at: EngineLocation.supportDir, withIntermediateDirectories: true)
            if fm.fileExists(atPath: loc.engineDir.path) { try fm.removeItem(at: loc.engineDir) }
            try fm.copyItem(at: src, to: loc.engineDir)
            let s = EngineLocation.supportDir
            env["UV_PROJECT_ENVIRONMENT"] = loc.venvDir.path
            env["UV_PYTHON_INSTALL_DIR"] = s.appending(path: "python").path
            env["UV_CACHE_DIR"] = s.appending(path: "cache").path
        }
        step = "Installing Python and speech libraries (a few minutes the first time)"; progress = 0.15
        try await exec(uv, ["sync", "--frozen", "--no-dev", "--python", "3.12", "--python-preference", "only-managed"],
                       cwd: loc.engineDir, env: env)
        step = "Checking the install"; progress = 0.9
        try await exec(loc.python, ["-c", "import vox, faster_whisper, sounddevice; print('engine ok')"],
                       cwd: loc.engineDir, env: env)
    }

    private func exec(_ tool: URL, _ args: [String], cwd: URL, env: [String: String]) async throws {
        let p = Process()
        p.executableURL = tool
        p.arguments = args
        p.currentDirectoryURL = cwd
        p.environment = env
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe
        pipe.fileHandleForReading.readabilityHandler = { [weak self] h in
            let chunk = String(decoding: h.availableData, as: UTF8.self)
            guard !chunk.isEmpty else { return }
            Task { @MainActor in self?.ingest(chunk) }
        }
        try p.run()
        await withCheckedContinuation { (c: CheckedContinuation<Void, Never>) in
            p.terminationHandler = { _ in c.resume() }
        }
        pipe.fileHandleForReading.readabilityHandler = nil
        if p.terminationStatus != 0 {
            throw Failure("\(tool.lastPathComponent) failed (exit \(p.terminationStatus)). \(lines.last ?? "")")
        }
    }

    private func ingest(_ chunk: String) {
        for line in chunk.split(whereSeparator: \.isNewline) where !line.trimmingCharacters(in: .whitespaces).isEmpty {
            lines.append(String(line))
            // uv prints "Prepared N packages" / "Installed N packages": nudge the bar along.
            if line.contains("Prepared") { progress = max(progress, 0.6) }
            if line.contains("Installed") { progress = max(progress, 0.85) }
        }
        if lines.count > 400 { lines.removeFirst(lines.count - 400) }
    }

    /// Developer checkouts may not ship a bundled uv; fall back to the user's.
    private static func systemUV() -> URL? {
        for dir in EngineLocation.childPATH.split(separator: ":") {
            let u = URL(fileURLWithPath: String(dir)).appending(path: "uv")
            if FileManager.default.isExecutableFile(atPath: u.path) { return u }
        }
        return nil
    }

    struct Failure: LocalizedError {
        var message: String
        init(_ m: String) { message = m }
        var errorDescription: String? { message }
    }
}
