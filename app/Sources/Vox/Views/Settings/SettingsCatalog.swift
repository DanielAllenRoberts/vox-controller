import Foundation

/// How the engine's flat list of ~50 settings is presented: which tab and section each one lives
/// in, and a plain-English name and one-line explanation. The engine's own label and help are the
/// fallback (help also shows as a tooltip). A setting the catalog doesn't know about still appears,
/// under Advanced → Other, so nothing added to the engine can go missing.
enum SettingsTab: String, CaseIterable, Identifiable {
    case general, listening, voice, brains, control, permissions, advanced
    var id: String { rawValue }

    var title: String {
        switch self {
        case .general: "General"
        case .listening: "Listening"
        case .voice: "Voice"
        case .brains: "Brains"
        case .control: "Control"
        case .permissions: "Permissions"
        case .advanced: "Advanced"
        }
    }

    var symbol: String {
        switch self {
        case .general: "gearshape"
        case .listening: "ear"
        case .voice: "speaker.wave.2"
        case .brains: "brain"
        case .control: "hand.tap"
        case .permissions: "hand.raised"
        case .advanced: "wrench.and.screwdriver"
        }
    }
}

struct SettingSpec {
    var key: String
    var label: String
    var caption: String?
}

struct SettingsSection {
    var title: String
    var footer: String?
    var items: [SettingSpec]
}

enum SettingsCatalog {
    private static func s(_ key: String, _ label: String, _ caption: String? = nil) -> SettingSpec {
        SettingSpec(key: key, label: label, caption: caption)
    }

    static let tabs: [SettingsTab: [SettingsSection]] = [
        .general: [
            .init(title: "Replies", footer: nil, items: [
                s("tts_enabled", "Speak replies", "Vox answers out loud. Turn off to read replies in the bubble instead."),
            ]),
            .init(title: "Notification bubble", footer: "The quiet card Vox and your agents use instead of speaking.", items: [
                s("bubble_corner", "Position"),
                s("bubble_duration", "Stays on screen (seconds)", "0 keeps it until you close it."),
                s("bubble_max_width", "Width (points)"),
            ]),
            .init(title: "Coding agents", footer: "Needs the Vox hook in Claude Code's settings (see mcp/README.md).", items: [
                s("agent_alerts", "When an agent is waiting for you", "Says which agent needs you, e.g. \u{201C}David needs your OK.\u{201D}"),
                s("agent_done_alerts", "Also tell me when an agent finishes"),
            ]),
            .init(title: "Spending", footer: nil, items: [
                s("monthly_budget_usd", "Monthly budget (USD)", "Warns you as API spending approaches this. 0 turns it off."),
            ]),
        ],
        .listening: [
            .init(title: "Microphone", footer: nil, items: [
                s("input_device", "Input"),
                s("audio_aec", "Echo cancellation", "Lets Vox hear you over its own voice on speakers. Not needed with headphones."),
            ]),
            .init(title: "Knowing when you've finished", footer: nil, items: [
                s("turn_detection", "End of sentence", "Smart waits through thinking pauses; Silence is faster and simpler."),
                s("dictation_exit_on_silence", "Stop dictating after a long silence"),
                s("dictation_idle_exit_seconds", "Silence before dictation stops (seconds)"),
            ]),
            .init(title: "Interrupting Vox", footer: "Talk over Vox to stop it mid-sentence.", items: [
                s("barge_in_enabled", "Interrupt by speaking"),
                s("tts_interruptible", "Stop speaking when interrupted"),
                s("interrupt_slow_calls_only", "Only while it's thinking for a while"),
                s("interrupt_min_words", "Words needed to interrupt"),
                s("interrupt_min_seconds", "Speech needed to interrupt (seconds)"),
            ]),
            .init(title: "Recognition", footer: nil, items: [
                s("vosk_commands_enabled", "Instant commands", "Recognises known commands in milliseconds, before full transcription."),
                s("idle_speech_gate", "Ignore non-speech sounds while idle", "Saves CPU: coughs, clicks and doors aren't transcribed."),
                s("idle_speech_gate_ms", "Speech needed to listen (ms)"),
                s("idle_wake_precheck", "Quick wake-word check while idle", "Saves most idle CPU in a chatty room. May miss a fast \u{201C}Vox, open…\u{201D}."),
            ]),
        ],
        .voice: [
            .init(title: "Vox's voice", footer: nil, items: [
                s("tts_engine", "Voice engine", "Kokoro sounds natural and runs on this Mac. System uses macOS voices."),
                s("kokoro_voice", "Voice"),
            ]),
            .init(title: "Your agents' voice", footer: "Coding agents speak through Vox with a different voice, so you can tell them apart.", items: [
                s("mcp_tts_engine", "Voice engine"),
                s("mcp_kokoro_voice", "Natural voice"),
                s("mcp_tts_voice", "System voice name"),
                s("mcp_speak_cue", "Sound before speaking"),
            ]),
            .init(title: "Taking turns", footer: nil, items: [
                s("speech_queue_enabled", "One voice at a time", "Vox and agents wait for each other instead of talking over one another."),
                s("speech_queue_timeout", "Longest wait for a turn (seconds)"),
                s("speech_queue_max_hold", "Longest anyone can hold the floor (seconds)"),
            ]),
        ],
        .brains: [
            .init(title: "Quick replies", footer: "Handles everyday commands and chat. Should be fast and cheap.", items: [
                s("small_brain_provider", "Provider"),
                s("small_brain_model", "Model"),
                s("small_brain_thinking", "Think before answering", "Off is about twice as fast. On is more careful with vague requests."),
            ]),
            .init(title: "Hard questions", footer: "Takes over when the quick brain needs help, and for looking at the screen.", items: [
                s("big_brain_provider", "Provider"),
                s("big_brain_model", "Model"),
                s("escalate_to_big_brain", "Hand hard questions to this brain"),
                s("escalation_mode", "When to hand over"),
            ]),
            .init(title: "Screen agent", footer: "For multi-step tasks Vox has to see the screen to do.", items: [
                s("agent_enabled", "Allow multi-step tasks"),
                s("agent_model", "Model"),
                s("agent_effort", "Effort"),
                s("agent_max_steps", "Most steps per task"),
            ]),
        ],
        .control: [
            .init(title: "Acting for you", footer: nil, items: [
                s("llm_executor_enabled", "Work out unfamiliar commands", "When Vox doesn't recognise a command, the brain figures out what to do."),
                s("click_vision_fallback", "Find buttons by looking", "If a button can't be found by name, Vox looks at the screen."),
                s("screen_vision_enabled", "Answer questions about the screen"),
                s("screen_vision_mode", "How Vox reads the screen"),
            ]),
            .init(title: "Typing", footer: "Like Dragon: in a text box, what you say is typed unless the whole sentence is a command. Say \u{201C}scratch that\u{201D} to undo.", items: [
                s("auto_dictation", "Type automatically in text fields"),
            ]),
            .init(title: "Commands", footer: nil, items: [
                s("command_db_enabled", "Per-app commands", "Commands can mean different things in different apps."),
                s("learning_mode", "Learn new commands", "Remembers commands the brain works out, so they're instant next time."),
                s("learning_confirm", "Ask before saving a new command"),
            ]),
            .init(title: "Learning", footer: "How sure Vox must be before a learned command sticks.", items: [
                s("learning_min_hits", "Times seen before learning"),
                s("learning_window_days", "Within this many days"),
                s("learning_probation_days", "Trial period (days)"),
                s("learning_probation_uses", "Uses to pass the trial"),
            ]),
            .init(title: "Memory", footer: nil, items: [
                s("memory_autocapture", "Remember things on its own", "Vox notes facts you mention (with your memory page to review them)."),
            ]),
        ],
        .advanced: [
            .init(title: "Diagnostics", footer: nil, items: [
                s("debug", "Detailed log", "Writes every prompt and decision to vox.log."),
                s("command_db_log", "Log command lookups"),
            ]),
        ],
    ]

    static let knownKeys: Set<String> = Set(tabs.values.flatMap { $0.flatMap { $0.items.map(\.key) } })

    /// Engine settings whose help says they only apply after a restart.
    static func needsRestart(_ s: Setting) -> Bool { s.help.localizedCaseInsensitiveContains("restart to apply") }
}
