import Foundation

/// Talks to the engine's bridge on localhost. Every mutation sends a JSON body with a JSON content
/// type: the engine refuses state-changing requests without one (CSRF guard), so even a bodyless
/// POST sends `{}`.
struct APIClient {
    var port: Int = 8765

    struct APIError: LocalizedError {
        var status: Int
        var message: String
        var errorDescription: String? { message }
    }

    private var base: URL { URL(string: "http://127.0.0.1:\(port)/api")! }

    private static let session: URLSession = {
        let c = URLSessionConfiguration.ephemeral
        c.timeoutIntervalForRequest = 8
        c.waitsForConnectivity = false
        return URLSession(configuration: c)
    }()

    func get<T: Decodable>(_ path: String, as: T.Type = T.self) async throws -> T {
        try await send(path, method: "GET", body: Optional<[String: String]>.none)
    }

    @discardableResult
    func send<T: Decodable, B: Encodable>(_ path: String, method: String, body: B?) async throws -> T {
        var req = URLRequest(url: base.joined(path))
        req.httpMethod = method
        if method != "GET" {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try body.map { try JSONEncoder().encode($0) } ?? Data("{}".utf8)
        }
        let (data, resp) = try await Self.session.data(for: req)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(code) else {
            let msg = (try? JSONDecoder().decode([String: JSONValue].self, from: data))
                .flatMap { $0["error"]?.string ?? $0["detail"]?.string } ?? "Request failed (\(code))"
            throw APIError(status: code, message: msg)
        }
        if T.self == Empty.self { return Empty() as! T }
        return try JSONDecoder().decode(T.self, from: data)
    }

    func post(_ path: String, _ body: [String: JSONValue] = [:]) async throws {
        let _: Empty = try await send(path, method: "POST", body: body)
    }

    func patch(_ path: String, _ body: [String: JSONValue]) async throws {
        let _: Empty = try await send(path, method: "PATCH", body: body)
    }

    func delete(_ path: String) async throws {
        let _: Empty = try await send(path, method: "DELETE", body: Optional<[String: String]>.none)
    }

    // MARK: Typed helpers

    func status() async throws -> EngineStatus { try await get("status") }
    func settings() async throws -> [Setting] { try await get("settings") }
    func setSetting(_ key: String, _ value: JSONValue) async throws { try await post("settings", ["key": .string(key), "value": value]) }
    func say(_ text: String) async throws { try await post("say", ["text": .string(text)]) }
    func setPaused(_ paused: Bool) async throws { try await post("listening", ["paused": .bool(paused)]) }
    /// The stop button: halts speech, a pending brain call and any agent run. Returns what stopped.
    func stop() async throws -> [String] {
        struct R: Decodable { var stopped: [String] }
        let r: R = try await send("stop", method: "POST", body: [String: JSONValue]())
        return r.stopped
    }
    func restart() async throws { try await post("restart") }
    func recentTurns(_ limit: Int = 200) async throws -> [Turn] { try await get("conversation/recent?limit=\(limit)") }

    /// URL for the live conversation websocket.
    var conversationStream: URL { URL(string: "ws://127.0.0.1:\(port)/api/conversation/stream")! }

    /// URL for the corner indicator's live events (listening / heard / mode changed).
    var hudStream: URL { URL(string: "ws://127.0.0.1:\(port)/api/hud/stream")! }
}

/// Decodes any (or no) response body. Used where only success matters.
struct Empty: Codable { init() {}; init(from decoder: Decoder) throws {} }

extension URL {
    /// Appends an API path that may carry a query string ("x?limit=5"); `appending(path:)` would escape the "?".
    func joined(_ path: String) -> URL {
        let parts = path.split(separator: "?", maxSplits: 1).map(String.init)
        var url = self.appending(path: parts[0])
        if parts.count == 2, var c = URLComponents(url: url, resolvingAgainstBaseURL: false) {
            c.percentEncodedQuery = parts[1]
            url = c.url ?? url
        }
        return url
    }
}
