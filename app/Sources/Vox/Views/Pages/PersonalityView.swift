import SwiftUI

/// Who Vox is when it talks: pick a character, make your own, choose how it sounds.
struct PersonalityView: View {
    @Environment(AppModel.self) private var model
    @State private var data: Personalities?
    @State private var sayVoices: [String] = []
    @State private var error: String?
    @State private var editing: EditTarget?
    @State private var pendingDelete: Personality?

    enum EditTarget: Identifiable {
        case new, edit(Personality)
        var id: String { if case .edit(let p) = self { p.id } else { "new" } }
    }

    private let columns = [GridItem(.adaptive(minimum: 200), spacing: 12)]

    var body: some View {
        RequiresEngine {
            Group {
                if let data { content(data) } else { PageLoading() }
            }
            .inlineError($error)
            .toolbar {
                ToolbarItem {
                    Button("New Personality", systemImage: "plus") { editing = .new }
                        .help("Make your own personality")
                }
            }
            .sheet(item: $editing) { target in
                PersonaEditor(original: target.persona, voices: voiceChoices, onSave: save)
            }
            .confirmationDialog("Delete \u{201C}\(pendingDelete?.name ?? "")\u{201D}?", isPresented: deleteBinding,
                                titleVisibility: .visible, presenting: pendingDelete) { p in
                Button("Delete Personality", role: .destructive) { delete(p) }
            } message: { p in
                Text(p.id == data?.active ? "Vox will go back to its default personality." : "This can't be undone.")
            }
            .task { await load() }
        }
    }

    private func content(_ data: Personalities) -> some View {
        let all = data.presets + data.custom
        let active = all.first { $0.id == data.active } ?? data.presets.first
        return PageScroll {
            if let active {
                ActivePersonaCard(persona: active, voices: voiceChoices,
                                  onVoice: { setVoice(active, $0) },
                                  onEdit: active.preset ? nil : { editing = .edit(active) })
            }

            SectionLabel("Characters").padding(.top, Metrics.tight)
            LazyVGrid(columns: columns, spacing: 12) {
                ForEach(data.presets) { tile($0, active: $0.id == data.active) }
            }

            SectionLabel("Your Personalities").padding(.top, Metrics.tight)
            LazyVGrid(columns: columns, spacing: 12) {
                ForEach(data.custom) { tile($0, active: $0.id == data.active) }
                NewPersonaTile { editing = .new }
            }
        }
    }

    private func tile(_ p: Personality, active: Bool) -> some View {
        PersonaTile(persona: p, active: active) { activate(p) }
            .contextMenu {
                Button("Use \(p.name)") { activate(p) }.disabled(active)
                if !p.preset {
                    Button("Edit…") { editing = .edit(p) }
                    Divider()
                    Button("Delete…", role: .destructive) { pendingDelete = p }
                }
            }
    }

    private var voiceChoices: VoiceChoices {
        let kokoro = model.value("tts_engine").string == "kokoro"
        return VoiceChoices(kokoro: kokoro,
                            names: kokoro ? (model.setting("kokoro_voice")?.options ?? []).map(\.value) : sayVoices)
    }

    private var deleteBinding: Binding<Bool> {
        Binding(get: { pendingDelete != nil }, set: { if !$0 { pendingDelete = nil } })
    }

    // MARK: Data

    private func load() async {
        do {
            data = try await model.api.get("personalities")
            error = nil
        } catch {
            self.error = "Couldn't load personalities. \(error.localizedDescription)"
            if data == nil { data = Personalities(active: "", presets: [], custom: []) }
        }
        if sayVoices.isEmpty, let v: [String: [String]] = try? await model.api.get("voices") { sayVoices = v["voices"] ?? [] }
    }

    private func activate(_ p: Personality) {
        guard data?.active != p.id else { return }
        withAnimation(.smooth) { data?.active = p.id }
        Task {
            do { try await model.api.post("personalities/active", ["id": .string(p.id)]) }
            catch { self.error = "Couldn't switch to \(p.name). \(error.localizedDescription)"; await load() }
        }
    }

    private func setVoice(_ p: Personality, _ voice: String) {
        let key = voiceChoices.kokoro ? "kokoroVoice" : "suggestedVoice"
        Task {
            do { try await model.api.patch("personalities/\(p.id)/voice", [key: .string(voice)]); await load() }
            catch { self.error = "Couldn't change the voice. \(error.localizedDescription)"; await load() }
        }
    }

    /// Creates or updates a custom personality. Returns an error message for the sheet, or nil.
    private func save(_ original: Personality?, _ draft: PersonaDraft) async -> String? {
        var body: [String: JSONValue] = [
            "name": .string(draft.name), "emoji": .string(draft.emoji),
            "tagline": .string(draft.tagline), "persona": .string(draft.persona),
        ]
        body[voiceChoices.kokoro ? "kokoroVoice" : "suggestedVoice"] = .string(draft.voice)
        do {
            if let original { try await model.api.patch("personalities/custom/\(original.id)", body) }
            else { try await model.api.post("personalities/custom", body) }
            await load()
            return nil
        } catch {
            return error.localizedDescription
        }
    }

    private func delete(_ p: Personality) {
        withAnimation(.smooth) { data?.custom.removeAll { $0.id == p.id } }
        Task {
            do { try await model.api.delete("personalities/custom/\(p.id)") }
            catch { self.error = "Couldn't delete \(p.name). \(error.localizedDescription)" }
            await load()
        }
    }
}

private extension PersonalityView.EditTarget {
    var persona: Personality? { if case .edit(let p) = self { p } else { nil } }
}

// MARK: Voices

/// The voices on offer for the speech engine Vox is using right now.
struct VoiceChoices {
    var kokoro: Bool
    var names: [String]

    func current(_ p: Personality) -> String { (kokoro ? p.kokoroVoice : p.suggestedVoice) ?? "" }

    /// Kokoro ids read "af_bella": accent, gender, name.
    static func friendly(_ id: String) -> String {
        let parts = id.split(separator: "_", maxSplits: 1)
        guard parts.count == 2 else { return id }
        return parts[1].capitalized
    }

    static func group(_ id: String) -> String {
        guard id.count > 2, id.dropFirst(2).first == "_" else { return "Other" }
        let accent = ["a": "American", "b": "British"][String(id.prefix(1))]
        let gender = ["f": "Female", "m": "Male"][String(id.dropFirst().prefix(1))]
        guard let accent, let gender else { return "Other Accents" }
        return "\(accent) \(gender)"
    }
}

struct VoicePicker: View {
    var title: String
    var choices: VoiceChoices
    @Binding var selection: String

    var body: some View {
        Picker(title, selection: $selection) {
            Text("Vox's usual voice").tag("")
            Divider()
            if choices.kokoro {
                let names = withCurrent
                let groups = Dictionary(grouping: names, by: VoiceChoices.group)
                ForEach(groups.keys.sorted(), id: \.self) { g in
                    Section(g) {
                        ForEach(groups[g] ?? [], id: \.self) { Text(VoiceChoices.friendly($0)).tag($0) }
                    }
                }
            } else {
                ForEach(withCurrent, id: \.self) { Text($0).tag($0) }
            }
        }
    }

    /// The saved voice always stays selectable, even if it's no longer offered.
    private var withCurrent: [String] {
        selection.isEmpty || choices.names.contains(selection) ? choices.names : [selection] + choices.names
    }
}

// MARK: Active card

private struct ActivePersonaCard: View {
    var persona: Personality
    var voices: VoiceChoices
    var onVoice: (String) -> Void
    var onEdit: (() -> Void)?
    @State private var expanded = false
    @State private var truncated = false

    private var isDefault: Bool { persona.persona.isEmpty }

    var body: some View {
        Card(padding: 20) {
            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 16) {
                    Text(persona.emoji)
                        .font(.system(size: 34))
                        .frame(width: 64, height: 64)
                        .background(Color.accentColor.opacity(0.12), in: Circle())
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Vox is speaking as").font(.caption).foregroundStyle(.secondary)
                        Text(persona.name).font(.title2.weight(.semibold))
                        if !persona.tagline.isEmpty {
                            Text(persona.tagline).foregroundStyle(.secondary)
                        }
                    }
                    Spacer(minLength: 12)
                    if let onEdit { Button("Edit…", action: onEdit) }
                }

                if !isDefault {
                    Divider()
                    VStack(alignment: .leading, spacing: 6) {
                        Text(persona.persona)
                            .foregroundStyle(.secondary)
                            .lineLimit(expanded ? nil : 3)
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background { truncationProbe }
                        if truncated || expanded {
                            Button(expanded ? "Show Less" : "Show More") { withAnimation(.smooth) { expanded.toggle() } }
                                .buttonStyle(.link).font(.callout)
                        }
                    }
                    Divider()
                    HStack {
                        Label("Voice", systemImage: "waveform").foregroundStyle(.secondary)
                        Spacer()
                        VoicePicker(title: "Voice", choices: voices,
                                    selection: Binding(get: { voices.current(persona) }, set: onVoice))
                            .labelsHidden()
                            .fixedSize()
                    }
                }
            }
        }
        .onChange(of: persona.id) { _, _ in expanded = false }
    }

    /// Compares the clamped text with its full height to learn whether "Show More" has anything to show.
    private var truncationProbe: some View {
        GeometryReader { clamped in
            Text(persona.persona)
                .fixedSize(horizontal: false, vertical: true)
                .frame(width: clamped.size.width, alignment: .leading)
                .hidden()
                .background(GeometryReader { full in
                    Color.clear.onAppear { update(full.size.height, clamped.size.height) }
                        .onChange(of: full.size.height) { _, h in update(h, clamped.size.height) }
                        .onChange(of: clamped.size.height) { _, c in update(full.size.height, c) }
                })
        }
        .hidden()
    }

    private func update(_ full: CGFloat, _ clamped: CGFloat) {
        if !expanded { truncated = full > clamped + 1 }
    }
}

// MARK: Tiles

private struct PersonaTile: View {
    var persona: Personality
    var active: Bool
    var onSelect: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: onSelect) {
            VStack(alignment: .leading, spacing: 6) {
                HStack(alignment: .top) {
                    Text(persona.emoji).font(.system(size: 26))
                    Spacer()
                    if active {
                        Image(systemName: "checkmark.circle.fill")
                            .font(.title3).foregroundStyle(Color.accentColor)
                            .transition(.scale.combined(with: .opacity))
                    }
                }
                Text(persona.name).font(.headline).lineLimit(1)
                Text(persona.tagline.isEmpty ? "Your own character" : persona.tagline)
                    .font(.callout).foregroundStyle(.secondary)
                    .lineLimit(2, reservesSpace: true)
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.background.secondary, in: shape)
            .overlay(shape.strokeBorder(active ? Color.accentColor : Color.secondary.opacity(hovering ? 0.45 : 0.2),
                                        lineWidth: active ? 2 : 1))
            .contentShape(shape)
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
        .animation(.smooth(duration: 0.2), value: active)
        .accessibilityAddTraits(active ? .isSelected : [])
        .help(active ? "\(persona.name) is speaking now" : "Use \(persona.name)")
    }

    private var shape: RoundedRectangle { RoundedRectangle(cornerRadius: Metrics.radius, style: .continuous) }
}

private struct NewPersonaTile: View {
    var action: () -> Void
    @State private var hovering = false

    /// Mirrors PersonaTile's layout so the two always line up in the grid.
    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 6) {
                Text(Image(systemName: "plus.circle")).font(.system(size: 26, weight: .light))
                Text("New Personality").font(.headline).lineLimit(1)
                Text("Describe a character in your own words")
                    .font(.callout).foregroundStyle(.secondary)
                    .lineLimit(2, reservesSpace: true)
            }
            .foregroundStyle(hovering ? Color.accentColor : Color.primary)
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .overlay(RoundedRectangle(cornerRadius: Metrics.radius, style: .continuous)
                .strokeBorder(Color.secondary.opacity(hovering ? 0.6 : 0.35), style: StrokeStyle(lineWidth: 1, dash: [5, 4])))
            .contentShape(RoundedRectangle(cornerRadius: Metrics.radius, style: .continuous))
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
        .help("Make your own personality")
    }
}

// MARK: Editor

struct PersonaDraft {
    var emoji = "✨"
    var name = ""
    var tagline = ""
    var persona = ""
    var voice = ""
}

private struct PersonaEditor: View {
    var original: Personality?
    var voices: VoiceChoices
    var onSave: (Personality?, PersonaDraft) async -> String?

    @Environment(\.dismiss) private var dismiss
    @State private var draft = PersonaDraft()
    @State private var error: String?
    @State private var saving = false

    private var valid: Bool {
        !draft.name.trimmingCharacters(in: .whitespaces).isEmpty
            && !draft.persona.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        VStack(spacing: 0) {
            Text(original == nil ? "New Personality" : "Edit \(original?.name ?? "Personality")")
                .font(.headline)
                .padding(.top, Metrics.gap + 4)
            Form {
                Section {
                    TextField("Name", text: $draft.name, prompt: Text("Captain Haddock"))
                    TextField("Emoji", text: $draft.emoji)
                    TextField("Tagline", text: $draft.tagline, prompt: Text("A few words that sum them up"))
                }
                Section {
                    TextEditor(text: $draft.persona)
                        .font(.body)
                        .scrollContentBackground(.hidden)
                        .frame(minHeight: 140)
                        .overlay(alignment: .topLeading) {
                            if draft.persona.isEmpty {
                                Text("For example: You are a cheerful sea captain. Keep answers short, and always get the facts right.")
                                    .foregroundStyle(.tertiary).padding(.leading, 5).allowsHitTesting(false)
                            }
                        }
                } header: {
                    Text("How they talk")
                } footer: {
                    Text("Describe the character in your own words. Vox stays helpful and accurate whatever the style.")
                        .foregroundStyle(.secondary)
                }
                Section {
                    VoicePicker(title: "Voice", choices: voices, selection: $draft.voice)
                }
                if let error {
                    Section { Label(error, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.orange) }
                }
            }
            .formStyle(.grouped)

            Divider()
            HStack {
                Spacer()
                Button("Cancel", role: .cancel) { dismiss() }.keyboardShortcut(.cancelAction)
                Button(original == nil ? "Create" : "Save", action: save)
                    .keyboardShortcut(.defaultAction)
                    .disabled(!valid || saving)
            }
            .padding(Metrics.gap)
        }
        .frame(width: 500, height: 560)
        .onAppear {
            if let p = original {
                draft = PersonaDraft(emoji: p.emoji, name: p.name, tagline: p.tagline, persona: p.persona, voice: voices.current(p))
            }
        }
    }

    private func save() {
        saving = true
        Task {
            error = await onSave(original, draft)
            saving = false
            if error == nil { dismiss() }
        }
    }
}
