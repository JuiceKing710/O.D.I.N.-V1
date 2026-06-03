import React, { useEffect, useState } from "react";
import { createTask, fetchTasks } from "../ipc/apiClient.js";
import { useAppState } from "../state/appContext.jsx";
import { useChatStore } from "../state/chatStore.js";

export function ProjectDashboard() {
  const tasks = useChatStore((state) => state.tasks);
  const setTasks = useChatStore((state) => state.setTasks);
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const { currentUser } = useAppState();

  useEffect(() => {
    fetchTasks(currentUser.username)
      .then(setTasks)
      .catch((err) => setError(err.message));
  }, [currentUser.username, setTasks]);

  async function handleSubmit(event) {
    event.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName || submitting) {
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const task = await createTask({
        description,
        name: trimmedName,
        username: currentUser.username,
      });
      setTasks([task, ...tasks.filter((current) => current.task_id !== task.task_id)]);
      setName("");
      setDescription("");
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="panel" aria-label="Projects">
      <header>
        <h1>Projects</h1>
      </header>
      <form className="project-form" onSubmit={handleSubmit}>
        <label>
          Project
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Build voice workflow"
          />
        </label>
        <label>
          Notes
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="What should Jarvis track?"
            rows={3}
          />
        </label>
        <button type="submit" disabled={!name.trim() || submitting}>
          {submitting ? "Creating" : "Create"}
        </button>
      </form>
      {error && <p className="error">{error}</p>}
      {tasks.length ? (
        <ul className="task-list">
          {tasks.map((task) => (
            <li key={task.task_id}>
              <span>{task.name}</span>
              <small>{task.status}</small>
            </li>
          ))}
        </ul>
      ) : (
        <div className="empty-state">No active projects yet.</div>
      )}
    </section>
  );
}
