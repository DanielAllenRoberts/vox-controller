import AppKit
import SwiftUI

/// Guide: every Vox feature, what it does and how to use it. The permanent manual (Testing is the
/// temporary checklist). Content comes from the engine (`vox/guide.py`, GET /api/guide).
struct GuideView: View {
    @Environment(AppModel.self) private var model
    @State private var sections: [GuideSection] = []
    @State private var query = ""
    @State private var error: String?
    @State private var loaded = false

    private var shown: [GuideSection] {
        let q = query.trimmingCharacters(in: .whitespaces).lowercased()
        guard !q.isEmpty else { return sections }
        return sections.compactMap { s in
            let items = s.items.filter { $0.searchText.contains(q) || s.title.lowercased().contains(q) }
            return items.isEmpty ? nil : GuideSection(title: s.title, symbol: s.symbol, items: items)
        }
    }

    var body: some View {
        RequiresEngine {
            PageScroll {
                header
                if let error {
                    Label(error, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red).font(.callout)
                }
                if !loaded {
                    ProgressView().frame(maxWidth: .infinity).padding(.top, 40)
                } else if shown.isEmpty {
                    ContentUnavailableView.search(text: query).padding(.top, 30)
                } else {
                    ForEach(shown) { section in
                        Label(section.title, systemImage: section.symbol)
                            .font(.title3.weight(.semibold))
                            .padding(.top, 8)
                        Card(padding: 0) {
                            VStack(spacing: 0) {
                                ForEach(Array(section.items.enumerated()), id: \.element.id) { i, item in
                                    GuideRow(item: item)
                                    if i < section.items.count - 1 { Divider().padding(.leading, Metrics.gap) }
                                }
                            }
                        }
                    }
                }
            }
            .searchable(text: $query, placement: .toolbar, prompt: "Search features or phrases")
        }
        .task { await load() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Everything Vox can do").font(.largeTitle.weight(.bold))
            Text("Say the phrases in quotes, or type them into the box on Home. Click a phrase to copy it.")
                .font(.callout).foregroundStyle(.secondary)
        }
    }

    private func load() async {
        do {
            sections = try await model.api.get("guide")
            error = nil
        } catch {
            self.error = "Couldn't load the guide: \(error.localizedDescription)"
        }
        loaded = true
    }
}

private struct GuideRow: View {
    var item: GuideItem
    @State private var copied: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(item.title).font(.headline)
            Text(item.what).font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            if let say = item.say, !say.isEmpty {
                FlowLayout(spacing: 6) {
                    ForEach(say, id: \.self) { phrase in
                        Button { copy(phrase) } label: {
                            Text(copied == phrase ? "Copied" : "\u{201C}\(phrase)\u{201D}")
                                .font(.callout)
                                .padding(.horizontal, 10).padding(.vertical, 4)
                                .background(Color.accentColor.opacity(0.12), in: Capsule())
                        }
                        .buttonStyle(.plain)
                        .help("Copy")
                    }
                }
            }
            if let how = item.how { detail("info.circle", how) }
            if let place = item.where_ { detail("rectangle.on.rectangle", place) }
            if let note = item.note { detail("exclamationmark.circle", note, tint: .orange) }
        }
        .padding(Metrics.gap)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func detail(_ symbol: String, _ text: String, tint: Color = .secondary) -> some View {
        Label {
            Text(text).fixedSize(horizontal: false, vertical: true)
        } icon: {
            Image(systemName: symbol).foregroundStyle(tint)
        }
        .font(.callout)
        .foregroundStyle(.secondary)
    }

    private func copy(_ phrase: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(phrase, forType: .string)
        copied = phrase
        Task {
            try? await Task.sleep(for: .seconds(1.2))
            if copied == phrase { copied = nil }
        }
    }
}

struct GuideSection: Codable, Identifiable, Hashable {
    var title: String
    var symbol: String
    var items: [GuideItem]
    var id: String { title }
}

struct GuideItem: Codable, Identifiable, Hashable {
    var title: String
    var what: String
    var say: [String]?
    var how: String?
    var where_: String?
    var note: String?
    var id: String { title }

    enum CodingKeys: String, CodingKey { case title, what, say, how, where_ = "where", note }

    var searchText: String {
        ([title, what, how ?? "", where_ ?? "", note ?? ""] + (say ?? [])).joined(separator: " ").lowercased()
    }
}
