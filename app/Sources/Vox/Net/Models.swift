import Foundation

// Wire types for the engine's bridge API (src/vox/web/server.py). Field names match the JSON.

/// A JSON scalar. Settings values are strings, booleans or numbers depending on the setting.
enum JSONValue: Codable, Hashable {
    case string(String), bool(Bool), number(Double), null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let n = try? c.decode(Double.self) { self = .number(n) }
        else { self = .string(try c.decode(String.self)) }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let s): try c.encode(s)
        case .bool(let b): try c.encode(b)
        case .number(let n): try c.encode(n)
        case .null: try c.encodeNil()
        }
    }

    var bool: Bool {
        switch self {
        case .bool(let b): return b
        case .string(let s): return ["true", "1", "yes", "on"].contains(s.lowercased())
        case .number(let n): return n != 0
        case .null: return false
        }
    }

    var string: String {
        switch self {
        case .string(let s): return s
        case .bool(let b): return b ? "true" : "false"
        case .number(let n): return n == n.rounded() && abs(n) < 1e12 ? String(Int(n)) : String(n)
        case .null: return ""
        }
    }

    var number: Double? {
        switch self {
        case .number(let n): return n
        case .string(let s): return Double(s)
        default: return nil
        }
    }
}

struct BrainRef: Codable, Hashable { var provider: String; var model: String }

struct EngineStatus: Codable, Equatable {
    var running: Bool
    var mode: String
    var modeSince: Double?
    var paused: Bool?
    var pid: Int?
    var version: String?
    var smallBrain: BrainRef
    var bigBrain: BrainRef
    var personality: String
    var uptimeSeconds: Double
    /// The engine's own view of its permissions (it can lag the app's until it restarts).
    var permissions: [String: Bool]?
}

struct Turn: Codable, Identifiable, Hashable {
    var id: String
    var session: String?
    var ts: String
    var role: String
    var text: String
    var brain: String?
    var kind: String?

    var isUser: Bool { role == "user" }
    var date: Date? { ISO8601.parse(ts) }
}

struct SettingOption: Codable, Hashable { var value: String; var label: String }

struct Setting: Codable, Identifiable, Hashable {
    var key: String
    var label: String
    var group: String
    var type: String
    var value: JSONValue
    var options: [SettingOption]?
    var help: String
    var id: String { key }
}

struct Personality: Codable, Identifiable, Hashable {
    var id: String
    var name: String
    var emoji: String
    var tagline: String
    var persona: String
    var suggestedVoice: String?
    var kokoroVoice: String?
    var preset: Bool
}

struct Personalities: Codable { var active: String; var presets: [Personality]; var custom: [Personality] }

struct Rule: Codable, Identifiable, Hashable { var id: String; var text: String; var enabled: Bool; var app: String? }

struct VocabEntry: Codable, Identifiable, Hashable { var id: String; var heard: String; var write: String; var enabled: Bool }

struct CommandPhrase: Codable, Identifiable, Hashable { var id: Int; var text: String; var isPrimary: Bool; var matchType: String }

struct Command: Codable, Identifiable, Hashable {
    var id: Int
    var intent: String
    var arg: String?
    var param: String?
    var label: String
    var source: String
    var enabled: Bool
    var priority: Int
    var phrases: [CommandPhrase]
}

struct CommandContext: Codable, Identifiable, Hashable {
    var id: Int
    var kind: String
    var matchValue: String?
    var displayName: String
    var priority: Int
    var enabled: Bool
    var commands: [Command]
}

struct CommandDb: Codable { var contexts: [CommandContext] }

struct LearnedCommand: Codable, Identifiable, Hashable {
    var id: Int
    var intent: String
    var arg: String?
    var label: String
    var context: String
    var phrases: [String]
    var enabled: Bool
    var hits: Int
    var probation: Bool
    var probation_days_left: Int?
    var probation_uses_left: Int?
    var learned_at: String?
    var last_used_at: String?
    var reason: String?
}

struct LearningCandidate: Codable, Identifiable, Hashable {
    var id: Int
    var intent: String
    var arg: String?
    var context: String
    var phrases: [String]
    var hits: Int
    var negatives: Int
    var blocked: Bool
    var bar: String
    var last_seen: String?
}

struct LearningView: Codable {
    var mode: String
    var aliases: [LearnedAlias]?
    var learned: [LearnedCommand]
    var candidates: [LearningCandidate]
}

struct Reminder: Codable, Identifiable, Hashable {
    var id: String
    var kind: String
    var text: String
    var fireAt: String
    var recurrence: String?
    var createdAt: String?
    var enabled: Bool
}

struct Memory: Codable, Identifiable, Hashable {
    var id: String
    var ts: String
    var text: String
    var tags: [String]
    var tier: String?
}

struct BoardCard: Codable, Identifiable, Hashable {
    var id: Int
    var listId: Int
    var title: String
    var body: String
    var tags: [String]
    var position: Int
}

struct BoardList: Codable, Identifiable, Hashable { var id: Int; var name: String; var position: Int; var cards: [BoardCard] }

struct Board: Codable { var id: Int?; var name: String?; var lists: [BoardList] }

struct UsageTotals: Codable { var calls: Int; var inputTokens: Int; var outputTokens: Int; var costUsd: Double }
struct UsageByModel: Codable, Identifiable, Hashable {
    var model: String; var provider: String; var calls: Int; var inputTokens: Int; var outputTokens: Int; var costUsd: Double
    var id: String { provider + "/" + model }
}
struct UsageByDay: Codable, Identifiable, Hashable { var date: String; var costUsd: Double; var id: String { date } }
struct UsageSummary: Codable { var totals: UsageTotals; var byModel: [UsageByModel]; var byDay: [UsageByDay] }

struct UsageEvent: Codable, Identifiable, Hashable {
    var id: String; var ts: String; var provider: String; var model: String; var brain: String; var kind: String
    var inputTokens: Int; var outputTokens: Int; var costUsd: Double; var latencyMs: Double
}

enum ISO8601 {
    private static let frac: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]; return f
    }()
    private static let plain = ISO8601DateFormatter()
    private static let local: DateFormatter = {
        let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"; return f
    }()

    static func parse(_ s: String) -> Date? {
        frac.date(from: s) ?? plain.date(from: s) ?? local.date(from: String(s.prefix(19)))
    }
}

// MARK: Organise pages
// Types and helpers for Board, Reminders, Memory and Activity. Request bodies are typed structs so
// integers go over the wire as integers and arrays as arrays (JSONValue has neither).

struct BudgetStatus: Codable { var budgetUsd: Double; var spentUsd: Double; var remainingUsd: Double; var percent: Double; var state: String }

struct BoardMoveBody: Encodable { var toList: Int; var position: Int }
struct MemoryAddBody: Encodable { var text: String; var tier: String }
struct ReminderAddBody: Encodable { var kind: String; var text: String; var fireAt: String; var recurrence: String? }

extension APIClient {
    /// POST/PATCH with a typed body when only success matters.
    func send<B: Encodable>(_ path: String, method: String = "POST", _ body: B) async throws {
        let _: Empty = try await send(path, method: method, body: body)
    }
}

/// The scheduler speaks naive local ISO datetimes ("2026-06-19T21:30:00").
enum LocalISO {
    private static let f: DateFormatter = {
        let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"; return f
    }()
    private static let day: DateFormatter = {
        let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "yyyy-MM-dd"; return f
    }()
    static func string(_ d: Date) -> String { f.string(from: d) }
    static func date(_ s: String) -> Date? { f.date(from: String(s.prefix(19))) }
    /// "2026-06-19" as local midnight.
    static func day(_ s: String) -> Date? { day.date(from: String(s.prefix(10))) }
}

extension Reminder {
    var fireDate: Date? { LocalISO.date(fireAt) }
    var isRepeating: Bool { !(recurrence ?? "").isEmpty }
}

// MARK: Teach pages (Personality, Commands, Vocabulary, Rules)

/// A new way of saying something Vox already does: a learned phrase attached to an existing
/// command. `id` is the phrase's id, so it's removed with DELETE /commands/phrases/{id}.
struct LearnedAlias: Codable, Identifiable, Hashable {
    var id: Int
    var text: String
    var hits: Int
    var command_id: Int
    var label: String
    var intent: String
    var arg: String?
}

extension ISO8601 {
    /// The command DB's SQLite timestamps ("2026-10-17 14:42:34") are UTC without a zone.
    static func parseUTC(_ s: String?) -> Date? {
        guard let s, !s.isEmpty else { return nil }
        return s.contains("T") ? parse(s) : parse(s.replacingOccurrences(of: " ", with: "T") + "Z")
    }
}
