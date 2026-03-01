#!/usr/bin/env bun
/**
 * ACAP OpenTUI Frontend
 * Minimal two-pane terminal UI for ACAP prep flow.
 */

import { createCliRenderer, TextRenderable, BoxRenderable } from "@opentui/core";

// ============================================================================
// Ring Buffer for Logs
// ============================================================================

class RingBuffer<T> {
  private buffer: T[];
  private index = 0;
  private count = 0;

  constructor(private capacity: number) {
    this.buffer = new Array(capacity);
  }

  push(item: T): void {
    this.buffer[this.index] = item;
    this.index = (this.index + 1) % this.capacity;
    if (this.count < this.capacity) this.count++;
  }

  getAll(): T[] {
    if (this.count < this.capacity) return this.buffer.slice(0, this.count);
    const result: T[] = [];
    for (let i = 0; i < this.capacity; i++) {
      result.push(this.buffer[(this.index + i) % this.capacity]);
    }
    return result;
  }
}

// ============================================================================
// Main Application
// ============================================================================

async function main() {
  const renderer = await createCliRenderer({ exitOnCtrlC: true });
  const width = process.stdout.columns || 80;
  const height = process.stdout.rows || 24;

  // Create left pane (phases)
  const leftPane = new BoxRenderable(renderer, {
    id: "left",
    x: 0,
    y: 0,
    width: 30,
    height: height - 1,
    border: true,
    borderStyle: "single",
  });

  const titleText = new TextRenderable(renderer, {
    id: "title",
    x: 2,
    y: 1,
    content: "ACAP PREP FLOW",
    bold: true,
  });
  leftPane.add(titleText);

  // Phase list
  const phases = ["analyze", "qa", "generate", "write", "configure", "handoff"];
  phases.forEach((phase, i) => {
    const phaseText = new TextRenderable(renderer, {
      id: `phase-${phase}`,
      x: 2,
      y: 3 + i * 2,
      content: `[ ] ${phase.toUpperCase()}`,
    });
    leftPane.add(phaseText);
  });

  // Create right pane (content)
  const rightPane = new BoxRenderable(renderer, {
    id: "right",
    x: 30,
    y: 0,
    width: width - 30,
    height: height - 1,
    border: true,
    borderStyle: "single",
  });

  const statusText = new TextRenderable(renderer, {
    id: "status",
    x: 32,
    y: 1,
    content: "Status: Ready (Press Q to quit)",
  });

  renderer.root.add(leftPane);
  renderer.root.add(rightPane);
  renderer.root.add(statusText);

  // Handle keyboard input
  process.stdin.setRawMode(true);
  process.stdin.on("data", (key: Buffer) => {
    const char = key.toString();
    
    if (char === "q" || char === "Q") {
      renderer.stop();
      process.exit(0);
    }
    
    if (char === "r" || char === "R") {
      statusText.setContent("Status: Running workflow...");
      // TODO: Start backend
    }
  });

  console.log("ACAP OpenTUI Frontend");
  console.log("Press R to run, Q to quit");
}

main().catch(console.error);
