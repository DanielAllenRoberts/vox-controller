import Foundation

/// Where the Python engine lives and how to run it.
///
/// * **Checkout**: Vox.app was built inside a clone of the repo (or `VOX_ENGINE_DIR` points at
///   one). It runs `<repo>/.venv/bin/python -m vox` with the repo as its working directory, so
///   `data/` and `vox.log` stay exactly where they always were.
/// * **Installed**: a downloaded app. The engine source ships inside the bundle and is unpacked
///   to `~/Library/Application Support/Vox/engine`. Python and the dependencies are installed by
///   the bundled `uv` into `.../Vox/venv`, and user data lives in `.../Vox/data`.
struct EngineLocation: Equatable {
    enum Kind: Equatable { case checkout, installed }

    var kind: Kind
    /// Directory holding `pyproject.toml` + `src/vox`.
    var engineDir: URL
    /// The virtualenv's root.
    var venvDir: URL
    /// VOX_DATA_DIR for installed mode; nil means the engine's default (`<repo>/data`).
    var dataDir: URL?

    var python: URL { venvDir.appending(path: "bin/python") }
    var isReady: Bool { FileManager.default.isExecutableFile(atPath: python.path) }

    /// Effective data folder (for "Show in Finder" and the log).
    var resolvedDataDir: URL { dataDir ?? engineDir.appending(path: "data") }

    var logFile: URL {
        kind == .checkout ? engineDir.appending(path: "vox.log") : resolvedDataDir.appending(path: "vox.log")
    }

    static var supportDir: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appending(path: "Vox")
    }

    static func detect() -> EngineLocation {
        if let env = ProcessInfo.processInfo.environment["VOX_ENGINE_DIR"], !env.isEmpty {
            let dir = URL(fileURLWithPath: (env as NSString).expandingTildeInPath)
            return EngineLocation(kind: .checkout, engineDir: dir, venvDir: dir.appending(path: ".venv"), dataDir: nil)
        }
        if let repo = enclosingCheckout(of: Bundle.main.bundleURL) {
            return EngineLocation(kind: .checkout, engineDir: repo, venvDir: repo.appending(path: ".venv"), dataDir: nil)
        }
        let s = supportDir
        return EngineLocation(kind: .installed, engineDir: s.appending(path: "engine"),
                              venvDir: s.appending(path: "venv"), dataDir: s.appending(path: "data"))
    }

    /// Walks up from the app bundle looking for the repo root (pyproject.toml + src/vox).
    private static func enclosingCheckout(of url: URL) -> URL? {
        var dir = url.deletingLastPathComponent()
        let fm = FileManager.default
        for _ in 0..<6 {
            if fm.fileExists(atPath: dir.appending(path: "pyproject.toml").path),
               fm.fileExists(atPath: dir.appending(path: "src/vox/__init__.py").path) {
                return dir
            }
            let parent = dir.deletingLastPathComponent()
            if parent == dir { break }
            dir = parent
        }
        return nil
    }

    /// Engine source shipped inside the bundle (installed builds only).
    static var bundledEngine: URL? {
        let u = Bundle.main.resourceURL?.appending(path: "engine")
        return u.flatMap { FileManager.default.fileExists(atPath: $0.path) ? $0 : nil }
    }

    static var bundledUV: URL? {
        let u = Bundle.main.resourceURL?.appending(path: "bin/uv")
        return u.flatMap { FileManager.default.isExecutableFile(atPath: $0.path) ? $0 : nil }
    }

    /// PATH for child processes. A Finder-launched app gets a bare PATH, but the engine shells out
    /// to Homebrew tools and the `claude` CLI (Claude subscription brain), so add the usual places.
    static var childPATH: String {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let extra = ["\(home)/.local/bin", "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
        let current = (ProcessInfo.processInfo.environment["PATH"] ?? "").split(separator: ":").map(String.init)
        var seen = Set<String>()
        return (extra + current).filter { seen.insert($0).inserted }.joined(separator: ":")
    }
}
