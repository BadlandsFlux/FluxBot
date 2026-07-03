import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { api } from "../api";
import { useFlash } from "./Flash";
import Spinner from "./Spinner";

export default function TagsTab({ guildId, tags, prefix, onChange }) {
  const flash = useFlash();
  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleAdd(e) {
    e.preventDefault();
    if (!name.trim() || !content.trim()) return;
    setSubmitting(true);
    try {
      const result = await api.addTag(guildId, name.trim(), content.trim());
      onChange(result.tags);
      setName("");
      setContent("");
      flash(`Saved tag "${name.trim().toLowerCase()}".`);
    } catch (err) {
      flash(err.message, "error");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRemove(tagName) {
    try {
      const result = await api.removeTag(guildId, tagName);
      onChange(result.tags);
      flash(`Removed tag "${tagName}".`);
    } catch (err) {
      flash(err.message, "error");
    }
  }

  return (
    <>
      <div className="card">
        <h2>Add a tag</h2>
        <p className="muted small">
          Members can invoke <code>{prefix}&lt;name&gt;</code> to post the tag's content — handy for rules, FAQs,
          and links you repeat often.
        </p>
        <form onSubmit={handleAdd} className="settings-form">
          <label>
            Name
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="rules" required />
          </label>
          <label>
            Content
            <input
              type="text"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="Read the pinned message before posting."
              required
            />
          </label>
          <button className="btn btn-primary btn-small" type="submit" disabled={submitting}>
            {submitting ? <Spinner size={14} /> : <Plus size={14} />} Add tag
          </button>
        </form>
      </div>

      <div className="card">
        <h2>Existing tags</h2>
        {tags.length ? (
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Content</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {tags.map((t) => (
                <tr key={t.id}>
                  <td>
                    <code>
                      {prefix}
                      {t.name}
                    </code>
                  </td>
                  <td className="muted small">{t.content}</td>
                  <td>
                    <button className="btn btn-ghost btn-small btn-icon" onClick={() => handleRemove(t.name)}>
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">No tags yet — add one above.</p>
        )}
      </div>
    </>
  );
}
