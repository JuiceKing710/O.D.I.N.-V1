import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { OdinStage } from "./OdinStage.jsx";
import { useSystemStore } from "../state/systemStore.js";

describe("OdinStage", () => {
  it("renders live software and hardware nodes from telemetry", () => {
    useSystemStore.setState({
      metrics: {
        cpu_percent: 37,
        cpu_count: 10,
        memory: { percent: 64, used_bytes: 1, total_bytes: 2 },
        disk: { percent: 45, used_bytes: 1, total_bytes: 2 },
        network: { sent_bytes_per_sec: 1000, recv_bytes_per_sec: 124000 },
        battery: { percent: 78, plugged: false },
        uptime_seconds: 1000,
        sampled_at: new Date().toISOString(),
      },
      nodes: {
        reasoning_engine: { ok: true, label: "llama3.1:8b" },
        security_mesh: { ok: true, label: "0 pending approval(s)" },
      },
      activity: [],
    });

    render(<OdinStage />);

    expect(screen.getByText("O.D.I.N.")).toBeInTheDocument();
    expect(screen.getByText("Reasoning Engine")).toBeInTheDocument();
    expect(screen.getByText("llama3.1:8b")).toBeInTheDocument();
    expect(screen.getByText("Security Mesh")).toBeInTheDocument();
    expect(screen.getByText("37% · 10 cores")).toBeInTheDocument();
    expect(screen.getByText("78% · battery")).toBeInTheDocument();
    expect(screen.getByText("Local Storage")).toBeInTheDocument();
  });
});
