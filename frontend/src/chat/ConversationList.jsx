// Conversations, newest first, grouped Today / Yesterday / Earlier (design brief §5.3).
// There is no conversations endpoint: the list is built from the user's history (§16).
import Icon from '../components/Icon'
import { Button } from '../components/ui'
import { dayGroup, truncate } from '../lib/format'

/** History items (newest first) → [{id, title (first question), lastAt}], newest first. */
export function groupConversations(items) {
  const byId = new Map()
  for (const item of items) {
    if (!item.conversation_id) continue
    const c = byId.get(item.conversation_id) ?? { id: item.conversation_id, title: item.question,
      lastAt: item.timestamp_utc, firstAt: item.timestamp_utc }
    if (item.timestamp_utc <= c.firstAt) {
      c.firstAt = item.timestamp_utc
      c.title = item.question // the title is the FIRST question
    }
    if (item.timestamp_utc > c.lastAt) c.lastAt = item.timestamp_utc
    byId.set(item.conversation_id, c)
  }
  return [...byId.values()].sort((a, b) => (a.lastAt < b.lastAt ? 1 : -1))
}

export default function ConversationList({ conversations, activeId, onOpen, onNew, disabled }) {
  const groups = ['Today', 'Yesterday', 'Earlier']
    .map((g) => [g, conversations.filter((c) => dayGroup(c.lastAt) === g)])
    .filter(([, list]) => list.length)
  return (
    <div className="flex h-full flex-col">
      <div className="p-4">
        <Button className="w-full" onClick={onNew} disabled={disabled}><Icon name="plus" /> New chat</Button>
      </div>
      <nav aria-label="Conversations" className="flex-1 overflow-y-auto px-3 pb-3">
        {conversations.length === 0 && <p className="px-2 text-sm text-muted">No conversations yet.</p>}
        {groups.map(([group, list]) => (
          <div key={group} className="mb-3">
            <h3 className="px-2 py-1 text-xs font-semibold uppercase tracking-widest text-muted">{group}</h3>
            <ul>
              {list.map((c) => (
                <li key={c.id}>
                  <button type="button" onClick={() => onOpen(c.id)} disabled={disabled}
                    title={c.title}
                    className={`w-full truncate rounded-lg px-2 py-1.5 text-left text-sm ${
                      c.id === activeId ? 'bg-primary-subtle font-medium text-primary-ink' : 'hover:bg-surface-muted'}`}>
                    {truncate(c.title, 60)}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
      <p className="border-t border-line px-4 py-3 text-xs text-muted">Conversations are retained for auditability.</p>
    </div>
  )
}
