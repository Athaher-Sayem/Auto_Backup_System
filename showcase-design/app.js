// Read-only conceptual workflow notes; no backup or restore operations.
const phases = {
  source: { number: '01 / 03', icon: '◇', title: 'Know what you are saving.', text: 'The Bash configuration points at a source directory and backup destination. Review paths before running a real backup.', footer: 'CONFIGURATION / SOURCE + DESTINATION' },
  package: { number: '02 / 03', icon: '▤', title: 'Turn files into an archive.', text: 'The Bash entrypoint pipes tar through pv and gzip, then writes a timestamped .tar.gz file to the configured destination.', footer: 'BASH / TAR → PV → GZIP' },
  restore: { number: '03 / 03', icon: '↩', title: 'Treat restore as a separate decision.', text: 'The menu delegates restoration to scripts/restore.sh. Inspect the script and the destination before restoring real files.', footer: 'RESTORE / SOURCE REVIEW REQUIRED' }
};
document.querySelectorAll('[data-phase]').forEach(button => button.addEventListener('click', () => {
  const phase = phases[button.dataset.phase]; if (!phase) return;
  for (const [id, text] of Object.entries({ 'phase-num': phase.number, 'phase-icon': phase.icon, 'phase-title': phase.title, 'phase-text': phase.text, 'phase-foot': phase.footer })) document.getElementById(id).textContent = text;
  document.querySelectorAll('[data-phase]').forEach(node => node.setAttribute('aria-pressed', String(node === button)));
}));
