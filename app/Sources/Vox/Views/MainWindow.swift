import SwiftUI

struct MainWindow: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        NavigationSplitView {
            List(selection: $model.page) {
                ForEach(Page.sections, id: \.1) { title, pages in
                    Section {
                        ForEach(pages) { page in
                            Label(page.title, systemImage: page.symbol).tag(page)
                        }
                    } header: {
                        if let title { Text(title) }
                    }
                }
            }
            .navigationSplitViewColumnWidth(min: 190, ideal: 210, max: 260)
            .safeAreaInset(edge: .bottom) { SidebarStatus().padding(12) }
        } detail: {
            detail(for: model.page)
                .navigationTitle(model.page.title)
        }
        .frame(minWidth: 820, minHeight: 540)
    }

    @ViewBuilder
    private func detail(for page: Page) -> some View {
        switch page {
        case .home: HomeView()
        case .conversation: ConversationView()
        case .guide: GuideView()
        case .agents: AgentsView()
        case .personality: PersonalityView()
        case .commands: CommandsView()
        case .vocabulary: VocabularyView()
        case .rules: RulesView()
        case .board: BoardView()
        case .reminders: RemindersView()
        case .memory: MemoryView()
        case .activity: ActivityView()
        case .voiceLab: VoiceLabView()
        case .testing: TestingView()
        case .prompts: PromptsView()
        }
    }
}

/// Bottom of the sidebar: one line that always answers "is Vox working?".
private struct SidebarStatus: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let p = VoxPresence.from(engine: model.engine.state, status: model.engine.status)
        HStack(spacing: 10) {
            StatusOrb(presence: p, size: 9)
            VStack(alignment: .leading, spacing: 1) {
                Text(p.title).font(.callout.weight(.medium))
                if let s = model.engine.status {
                    Text(BrainNames.short(s.smallBrain)).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 10).padding(.vertical, 8)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}

/// Human names for providers and models ("Claude subscription", "DeepSeek V4 Flash").
enum BrainNames {
    static func provider(_ p: String, model: String = "") -> String {
        switch p {
        case "claude_sdk": "Claude subscription"
        case "claude_cli": "Claude CLI"
        case "anthropic": "Anthropic API"
        case "local_ai": "Local model"
        case "openai": model.lowercased().contains("deepseek") ? "DeepSeek" : "OpenAI-compatible"
        case "chatgpt": "ChatGPT"
        default: p
        }
    }

    static func model(_ m: String) -> String {
        let known: [String: String] = [
            "claude-haiku-4-5-20251001": "Claude Haiku 4.5",
            "claude-sonnet-4-6": "Claude Sonnet 4.6",
            "claude-sonnet-5": "Claude Sonnet 5",
            "claude-opus-4-8": "Claude Opus 4.8",
            "claude-opus-5": "Claude Opus 5",
            "deepseek-v4-flash": "DeepSeek V4 Flash",
            "deepseek-v4-pro": "DeepSeek V4 Pro",
            "deepseek-chat": "DeepSeek Chat",
        ]
        if let name = known[m] { return name }
        // "gpt-5.6-terra" → "GPT-5.6 Terra": OpenAI's ids, readable, without a table to keep current.
        if m.hasPrefix("gpt-") {
            let parts = m.dropFirst(4).split(separator: "-")
            return (["GPT-" + (parts.first.map(String.init) ?? "")] + parts.dropFirst().map { $0.capitalized }).joined(separator: " ")
        }
        return m
    }

    static func short(_ b: BrainRef) -> String { model(b.model) }

    /// Provider menu labels: what you're paying with, not the protocol.
    static func providerOption(_ p: String) -> String {
        switch p {
        case "claude_sdk": "Claude subscription (Pro / Max)"
        case "anthropic": "Anthropic API key"
        case "openai": "DeepSeek or another OpenAI-compatible API"
        case "chatgpt": "ChatGPT (OpenAI API key)"
        case "local_ai": "Local model (Ollama, LM Studio)"
        case "claude_cli": "Claude CLI"
        default: p
        }
    }
}
