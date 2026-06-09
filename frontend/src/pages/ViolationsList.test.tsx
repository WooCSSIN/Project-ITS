import { render, screen, fireEvent, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { BrowserRouter } from "react-router-dom";
import React, { useState, useEffect } from "react";

// ─── Controllable mock state ──────────────────────────────────────────────────

// Callback that the test can use to push data after mount
let onWsDataChange: ((data: unknown) => void) | null = null;

// We wrap useWebSocket to expose a way for tests to inject data at specific times
const MockUseWebSocket = () => {
  const [data, setData] = useState<unknown>(null);
  const [isConnected, setIsConnected] = useState(false);

  // Register the callback for tests to push data
  useEffect(() => {
    onWsDataChange = (newData: unknown) => {
      setData(newData);
      setIsConnected(true);
    };
    return () => { onWsDataChange = null; };
  }, []);

  return {
    data,
    isConnected,
    error: null as string | null,
    reconnectCount: 0,
    connect: vi.fn(),
    disconnect: vi.fn(),
    send: vi.fn(),
  };
};

vi.mock("@/hooks/useWebSocket", () => ({
  useWebSocket: () => MockUseWebSocket(),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => vi.fn(),
  };
});

global.fetch = vi.fn();

import ViolationsList from "./ViolationsList";

// ═══════════════════════════════════════════════════════════════════════════
// BUG 4 — ViolationsList realtime updates
// ═══════════════════════════════════════════════════════════════════════════

describe("BUG 4 - ViolationsList realtime updates", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    onWsDataChange = null;

    (global.fetch as any).mockResolvedValue({
      ok: true,
      json: async () => [],
    });
  });

  // ─────────────────────────────────────────────────────────────────────────
  // Task 17: Exploration test — Bug Condition
  // ─────────────────────────────────────────────────────────────────────────

  it("Task 17: Bug Condition — wsData auto-prepends new violation into list", async () => {
    // Mount: initial fetch returns empty list
    render(<BrowserRouter><ViolationsList /></BrowserRouter>);
    await act(async () => { await new Promise((r) => setTimeout(r, 50)); });

    // Verify empty state
    expect(screen.getByText("Không có vi phạm nào.")).toBeInTheDocument();

    // Now simulate WebSocket pushing a new violation AFTER mount
    const wsViolation = {
      id: 9999,
      camera_id: 2,
      timestamp: new Date().toISOString(),
      violation_type: "red_light",
      license_plate: "30A-99999",
      status: "pending",
    };

    // Push data through the mock's setState
    await act(async () => {
      onWsDataChange?.(wsViolation);
      await new Promise((r) => setTimeout(r, 50));
    });

    // FIXED code: useEffect([wsData]) fires → prepends → #9999 visible
    // UNFIXED code: no useEffect watching wsData → #9999 never appears
    const found = screen.queryByText("#9999");
    expect(found).not.toBeNull();
  });

  // ─────────────────────────────────────────────────────────────────────────
  // Task 18: Preservation tests
  // ─────────────────────────────────────────────────────────────────────────

  it("Task 18: Preservation — fetchViolations is called on mount and when statusFilter changes", async () => {
    render(<BrowserRouter><ViolationsList /></BrowserRouter>);
    await act(async () => { await new Promise((r) => setTimeout(r, 10)); });

    expect(global.fetch).toHaveBeenCalledTimes(1);

    const select = screen.getByRole("combobox");
    fireEvent.change(select, { target: { value: "pending" } });
    await act(async () => { await new Promise((r) => setTimeout(r, 10)); });

    expect(global.fetch).toHaveBeenCalledTimes(2);
    expect((global.fetch as any).mock.calls[1][0]).toContain("status=pending");
  });

  it("Task 18: Preservation — manual refresh button calls fetchViolations", async () => {
    render(<BrowserRouter><ViolationsList /></BrowserRouter>);
    await act(async () => { await new Promise((r) => setTimeout(r, 10)); });

    expect(global.fetch).toHaveBeenCalledTimes(1);

    const refreshBtn = screen.getByRole("button", { name: /làm mới/i });
    fireEvent.click(refreshBtn);
    await act(async () => { await new Promise((r) => setTimeout(r, 10)); });

    expect(global.fetch).toHaveBeenCalledTimes(2);
  });
});
