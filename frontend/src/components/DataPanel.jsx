import React, { useEffect, useState } from "react";
import {
  deleteConversation,
  deleteMemoryDocument,
  exportConversation,
  fetchAuditEvents,
  fetchConversations,
  fetchMemoryBlocks,
  fetchMemoryDocuments,
  updateMemoryBlock,
} from "../ipc/apiClient.js";
import { useAppState } from "../state/appContext.jsx";

const BLOCK_LABELS = {
  persona: "Odin's persona",
  human: "About you",
};

export function DataPanel() {
  const { currentUser } = useAppState();
  const [auditEvents, setAuditEvents] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [documents, setDocuments] = useState([]);
  const [blocks, setBlocks] = useState({});
  const [blockDrafts, setBlockDrafts] = useState({});
  const [blockNotice, setBlockNotice] = useState("");
  const [error, setError] = useState("");

  async function refresh() {
    setError("");
    try {
      const [nextConversations, nextDocuments, nextAuditEvents, nextBlocks] = await Promise.all([
        fetchConversations(currentUser.username),
        fetchMemoryDocuments(currentUser.username),
        fetchAuditEvents(),
        fetchMemoryBlocks(),
      ]);
      setConversations(nextConversations);
      setDocuments(nextDocuments);
      setAuditEvents(nextAuditEvents);
      setBlocks(nextBlocks.blocks);
      setBlockDrafts(nextBlocks.blocks);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function handleBlockSave(label) {
    setBlockNotice("");
    setError("");
    try {
      const response = await updateMemoryBlock(label, blockDrafts[label] || "");
      setBlocks(response.blocks);
      setBlockDrafts(response.blocks);
      setBlockNotice(`${BLOCK_LABELS[label] || label} saved — Odin uses it in every reply.`);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  useEffect(() => {
    refresh();
  }, [currentUser.username]);

  async function handleConversationDelete(conversation) {
    if (!window.confirm(`Delete conversation "${conversation.title || conversation.convo_id}"?`)) {
      return;
    }
    try {
      await deleteConversation(conversation.convo_id, currentUser.username);
      await refresh();
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function handleConversationExport(conversation) {
    try {
      const exported = await exportConversation(conversation.convo_id, currentUser.username);
      const blob = new Blob([JSON.stringify(exported, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `jarvis-conversation-${conversation.convo_id}.json`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function handleDocumentDelete(document) {
    if (!window.confirm(`Delete memory "${document.source}"?`)) {
      return;
    }
    try {
      await deleteMemoryDocument(document.document_id, currentUser.username);
      await refresh();
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  return (
    <section className="panel" aria-label="Data management">
      <header className="section-heading">
        <div>
          <h1>Data</h1>
          <p>Manage conversations, long-term memory, and the local audit trail.</p>
        </div>
        <button type="button" onClick={refresh}>Refresh</button>
      </header>
      {error && <p className="error">{error}</p>}
      <div className="data-grid">
        <section className="settings-section core-memory-section">
          <div className="section-heading"><h2>Core Memory</h2><span>always in Odin's mind</span></div>
          {blockNotice && <p className="notice">{blockNotice}</p>}
          {Object.keys(BLOCK_LABELS).map((label) => (
            <div key={label} className="memory-block">
              <label>
                {BLOCK_LABELS[label]}
                <textarea
                  rows={3}
                  placeholder={
                    label === "human"
                      ? "Facts Odin should always know about you…"
                      : "How Odin carries himself…"
                  }
                  value={blockDrafts[label] ?? ""}
                  onChange={(event) =>
                    setBlockDrafts((drafts) => ({ ...drafts, [label]: event.target.value }))
                  }
                />
              </label>
              <button
                type="button"
                onClick={() => handleBlockSave(label)}
                disabled={(blockDrafts[label] ?? "") === (blocks[label] ?? "")}
              >
                Save
              </button>
            </div>
          ))}
        </section>
        <section className="settings-section">
          <div className="section-heading"><h2>Conversations</h2><span>{conversations.length}</span></div>
          <ul className="management-list">
            {conversations.map((conversation) => (
              <li key={conversation.convo_id}>
                <span><strong>{conversation.title || `Conversation ${conversation.convo_id}`}</strong><small>{conversation.message_count} messages</small></span>
                <div className="settings-actions">
                  <button type="button" onClick={() => handleConversationExport(conversation)}>Export</button>
                  <button type="button" onClick={() => handleConversationDelete(conversation)}>Delete</button>
                </div>
              </li>
            ))}
          </ul>
        </section>
        <section className="settings-section">
          <div className="section-heading"><h2>Memory</h2><span>{documents.length}</span></div>
          <ul className="management-list">
            {documents.map((document) => (
              <li key={document.document_id}>
                <span><strong>{document.source}</strong><small>{document.content.slice(0, 100)}</small></span>
                <button type="button" onClick={() => handleDocumentDelete(document)}>Delete</button>
              </li>
            ))}
          </ul>
        </section>
        <section className="settings-section audit-section">
          <div className="section-heading"><h2>Audit Log</h2><span>{auditEvents.length}</span></div>
          <ul className="management-list">
            {auditEvents.map((event, index) => (
              <li key={`${event.timestamp}-${index}`}>
                <span><strong>{event.action}</strong><small>{event.actor} · {event.result} · {new Date(event.timestamp).toLocaleString()}</small></span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </section>
  );
}
