// Teleport session: keeps <project>/.teleport-vscode/state.json equal to the editor's state (open
// tabs, active tab, cursors, scroll, unsaved edits) and restores it when VS Code starts. The file
// travels with the project checkpoint, so after a migration the editor reopens as it was.
'use strict';
const vscode = require('vscode');
const fs = require('fs');
const path = require('path');

let root = '';
let stateDir = '';
let statePath = '';
let lastJson = '';
let restoring = false;
let debounce = null;
const remembered = new Map(); // tab key -> { selections, top } for tabs that are not visible now

function rel(uri) {
  return path.relative(root, uri.fsPath).split(path.sep).join('/');
}

function keyOf(uri) {
  return uri.toString();
}

function snapshot() {
  const editors = [];
  for (const group of vscode.window.tabGroups.all) {
    for (const tab of group.tabs) {
      if (!(tab.input instanceof vscode.TabInputText)) continue;
      const uri = tab.input.uri;
      const doc = vscode.workspace.textDocuments.find((d) => keyOf(d.uri) === keyOf(uri));
      const entry = { column: group.viewColumn, active: tab.isActive && group.isActive, focused: tab.isActive };
      if (uri.scheme === 'untitled') {
        entry.untitled = true;
        entry.content = doc ? doc.getText() : '';
        entry.language = doc ? doc.languageId : 'plaintext';
      } else if (uri.scheme === 'file' && !path.relative(root, uri.fsPath).startsWith('..')) {
        entry.path = rel(uri);
        if (doc && doc.isDirty) entry.content = doc.getText();
      } else {
        continue;
      }
      const editor = vscode.window.visibleTextEditors.find((e) => keyOf(e.document.uri) === keyOf(uri));
      if (editor) {
        const view = {
          selections: editor.selections.map((s) => [s.anchor.line, s.anchor.character, s.active.line, s.active.character]),
          top: editor.visibleRanges.length ? editor.visibleRanges[0].start.line : 0,
        };
        remembered.set(keyOf(uri), view);
      }
      Object.assign(entry, remembered.get(keyOf(uri)) || {});
      editors.push(entry);
    }
  }
  return { v: 1, editors };
}

function write(force) {
  if (restoring || !root) return;
  try {
    const json = JSON.stringify(snapshot());
    if (!force && json === lastJson) return;
    fs.mkdirSync(stateDir, { recursive: true });
    const tmp = statePath + '.tmp';
    fs.writeFileSync(tmp, JSON.stringify({ ...JSON.parse(json), savedAt: Date.now() }, null, 1));
    fs.renameSync(tmp, statePath);
    lastJson = json;
  } catch (err) {
    console.error('[teleport] could not save the editor state', err);
  }
}

function soon() {
  if (debounce) clearTimeout(debounce);
  debounce = setTimeout(() => write(false), 250);
}

async function restore() {
  if (!fs.existsSync(statePath)) return;
  let state;
  try {
    state = JSON.parse(fs.readFileSync(statePath, 'utf8'));
  } catch {
    return;
  }
  restoring = true;
  let activeEditor = null;
  let activeEntry = null;
  try {
    for (const entry of state.editors || []) {
      try {
        const doc = entry.untitled
          ? await vscode.workspace.openTextDocument({ content: entry.content || '', language: entry.language || 'plaintext' })
          : await vscode.workspace.openTextDocument(vscode.Uri.file(path.join(root, ...entry.path.split('/'))));
        const editor = await vscode.window.showTextDocument(doc, {
          viewColumn: entry.column || vscode.ViewColumn.One,
          preview: false,
          preserveFocus: true,
        });
        if (!entry.untitled && typeof entry.content === 'string' && entry.content !== doc.getText()) {
          const all = new vscode.Range(doc.positionAt(0), doc.positionAt(doc.getText().length));
          await editor.edit((b) => b.replace(all, entry.content)); // the unsaved edits come back as unsaved
        }
        applyView(editor, entry);
        if (Array.isArray(entry.selections)) {
          // Keep the restored cursor for this tab even when it goes to the background.
          remembered.set(keyOf(doc.uri), { selections: entry.selections, top: entry.top || 0 });
        }
        if (entry.active) {
          activeEditor = editor;
          activeEntry = entry;
        }
      } catch (err) {
        console.error('[teleport] could not reopen', entry.path || 'untitled', err);
      }
    }
    if (activeEditor) {
      const editor = await vscode.window.showTextDocument(activeEditor.document, {
        viewColumn: activeEditor.viewColumn,
        preview: false,
        preserveFocus: false,
      });
      applyView(editor, activeEntry);
    }
  } finally {
    restoring = false;
  }
  vscode.window.setStatusBarMessage('$(cloud-download) Teleport: editor restored', 6000);
}

function applyView(editor, entry) {
  if (Array.isArray(entry.selections) && entry.selections.length) {
    editor.selections = entry.selections.map(
      (s) => new vscode.Selection(new vscode.Position(s[0], s[1]), new vscode.Position(s[2], s[3])),
    );
  }
  if (typeof entry.top === 'number') {
    const pos = new vscode.Position(entry.top, 0);
    editor.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.AtTop);
  }
}

function watchFlushRequests(context) {
  // The Teleport job asks for a fresh state right before the migration freezes the editor.
  const request = path.join(stateDir, 'flush.request');
  const ack = path.join(stateDir, 'flush.ack');
  let handled = '';
  const timer = setInterval(() => {
    try {
      if (!fs.existsSync(request)) return;
      const seq = fs.readFileSync(request, 'utf8').trim();
      if (!seq || seq === handled) return;
      write(true);
      fs.writeFileSync(ack, seq);
      handled = seq;
    } catch {
      /* next tick */
    }
  }, 100);
  context.subscriptions.push({ dispose: () => clearInterval(timer) });
}

async function activate(context) {
  const folder = vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders[0];
  if (!folder) return;
  root = folder.uri.fsPath;
  stateDir = path.join(root, '.teleport-vscode');
  statePath = path.join(stateDir, 'state.json');
  await restore();
  write(true);
  context.subscriptions.push(
    vscode.workspace.onDidChangeTextDocument(soon),
    vscode.window.onDidChangeTextEditorSelection(soon),
    vscode.window.onDidChangeTextEditorVisibleRanges(soon),
    vscode.window.onDidChangeVisibleTextEditors(soon),
    vscode.window.tabGroups.onDidChangeTabs(soon),
    vscode.workspace.onDidSaveTextDocument(soon),
  );
  const periodic = setInterval(() => write(false), 1500);
  context.subscriptions.push({ dispose: () => clearInterval(periodic) });
  watchFlushRequests(context);
  // A permanent status bar item, so it is always visible that Teleport is tracking this editor.
  const item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 1000);
  item.text = '$(cloud-upload) Teleport';
  item.tooltip = 'Teleport is saving this editor (tabs, cursors, unsaved edits) so it can migrate.';
  item.show();
  context.subscriptions.push(item);
}

function deactivate() {
  write(true);
}

module.exports = { activate, deactivate };
