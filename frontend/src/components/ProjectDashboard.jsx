import React, { useEffect, useState } from "react";
import { createTask, deleteTask, fetchTasks, updateTask } from "../ipc/apiClient.js";
import { useAppState } from "../state/appContext.jsx";
import { useChatStore } from "../state/chatStore.js";

const TASK_STATUS_OPTIONS = ["pending", "in_progress", "complete"];

export function ProjectDashboard() {
  const tasks = useChatStore((state) => state.tasks);
  const setTasks = useChatStore((state) => state.setTasks);
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [editingDescription, setEditingDescription] = useState("");
  const [editingName, setEditingName] = useState("");
  const [editingStatus, setEditingStatus] = useState("pending");
  const [name, setName] = useState("");
  const [selectedTaskId, setSelectedTaskId] = useState(null);
  const [saving, setSaving] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const { currentUser } = useAppState();
  const selectedTask = tasks.find((task) => task.task_id === selectedTaskId) || tasks[0] || null;
  const activeTasks = tasks.filter((task) => task.status !== "complete");
  const completedTasks = tasks.filter((task) => task.status === "complete");

  useEffect(() => {
    fetchTasks(currentUser.username)
      .then(setTasks)
      .catch((err) => setError(err.message));
  }, [currentUser.username, setTasks]);

  useEffect(() => {
    if (!selectedTask && selectedTaskId !== null) {
      setSelectedTaskId(null);
    }
    if (!selectedTask) {
      setEditingDescription("");
      setEditingName("");
      setEditingStatus("pending");
      return;
    }
    setSelectedTaskId(selectedTask.task_id);
    setEditingDescription(selectedTask.description || "");
    setEditingName(selectedTask.name);
    setEditingStatus(selectedTask.status);
  }, [selectedTask, selectedTaskId]);

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
      setSelectedTaskId(task.task_id);
      setName("");
      setDescription("");
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleTaskUpdate(event) {
    event.preventDefault();
    if (!selectedTask || saving) {
      return;
    }
    setSaving(true);
    setError("");
    try {
      const task = await updateTask({
        description: editingDescription,
        name: editingName.trim(),
        status: editingStatus,
        taskId: selectedTask.task_id,
        username: currentUser.username,
      });
      setTasks(tasks.map((current) => (current.task_id === task.task_id ? task : current)));
      setSelectedTaskId(task.task_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleTaskDelete() {
    if (!selectedTask || !window.confirm(`Delete "${selectedTask.name}"?`)) {
      return;
    }
    setSaving(true);
    try {
      await deleteTask(selectedTask.task_id, currentUser.username);
      setTasks(tasks.filter((task) => task.task_id !== selectedTask.task_id));
      setSelectedTaskId(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  function renderTaskGroup(label, groupTasks) {
    return (
      <section className="task-group" aria-label={label}>
        <div className="task-group-heading">
          <h2>{label}</h2>
          <span>{groupTasks.length}</span>
        </div>
        {groupTasks.length ? (
          <ul className="task-list">
            {groupTasks.map((task) => (
              <li key={task.task_id}>
                <button
                  className={selectedTask?.task_id === task.task_id ? "active" : ""}
                  type="button"
                  onClick={() => setSelectedTaskId(task.task_id)}
                >
                  <span>{task.name}</span>
                  <small>{task.status}</small>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <div className="empty-state">No {label.toLowerCase()} tasks.</div>
        )}
      </section>
    );
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
        <div className="project-workspace">
          <div className="task-groups">
            {renderTaskGroup("Active", activeTasks)}
            {renderTaskGroup("Completed", completedTasks)}
          </div>
          <aside className="task-detail" aria-label="Task details">
            {selectedTask ? (
              <form onSubmit={handleTaskUpdate}>
                <div className="section-heading">
                  <h2>Task Details</h2>
                  <span>#{selectedTask.task_id}</span>
                </div>
                <label>
                  Name
                  <input
                    value={editingName}
                    onChange={(event) => setEditingName(event.target.value)}
                  />
                </label>
                <label>
                  Status
                  <select
                    value={editingStatus}
                    onChange={(event) => setEditingStatus(event.target.value)}
                  >
                    {TASK_STATUS_OPTIONS.map((status) => (
                      <option key={status} value={status}>
                        {status}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Notes
                  <textarea
                    value={editingDescription}
                    onChange={(event) => setEditingDescription(event.target.value)}
                    rows={6}
                  />
                </label>
                <button type="submit" disabled={!editingName.trim() || saving}>
                  {saving ? "Saving" : "Save"}
                </button>
                <button type="button" disabled={saving} onClick={handleTaskDelete}>
                  Delete
                </button>
              </form>
            ) : (
              <div className="empty-state">Select a task to edit details.</div>
            )}
          </aside>
        </div>
      ) : (
        <div className="empty-state">No active projects yet.</div>
      )}
    </section>
  );
}
