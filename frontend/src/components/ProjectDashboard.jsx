import React, { useEffect, useState } from "react";
import { fetchTasks } from "../ipc/apiClient.js";
import { useChatStore } from "../state/chatStore.js";

export function ProjectDashboard() {
  const tasks = useChatStore((state) => state.tasks);
  const setTasks = useChatStore((state) => state.setTasks);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchTasks()
      .then(setTasks)
      .catch((err) => setError(err.message));
  }, [setTasks]);

  return (
    <section className="panel" aria-label="Projects">
      <header>
        <h1>Projects</h1>
      </header>
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
