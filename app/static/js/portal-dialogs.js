(function () {
  const openers = document.querySelectorAll('[data-dialog-open]');
  if (!openers.length || typeof HTMLDialogElement === 'undefined') return;

  let activeTrigger = null;

  const focusDialog = (dialog) => {
    const focusable = dialog.querySelector('[data-dialog-close], button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    (focusable || dialog).focus();
  };

  const closeDialog = (dialog) => {
    if (!dialog || !dialog.open) return;
    dialog.close();
  };

  openers.forEach((opener) => {
    opener.addEventListener('click', () => {
      const dialog = document.getElementById(opener.dataset.dialogOpen);
      if (!dialog || typeof dialog.showModal !== 'function') return;
      activeTrigger = opener;
      dialog.showModal();
      focusDialog(dialog);
    });
  });

  document.querySelectorAll('dialog[data-portal-dialog]').forEach((dialog) => {
    dialog.addEventListener('click', (event) => {
      if (event.target === dialog) closeDialog(dialog);
    });

    dialog.addEventListener('close', () => {
      if (activeTrigger && typeof activeTrigger.focus === 'function') activeTrigger.focus();
      activeTrigger = null;
    });

    dialog.querySelectorAll('[data-dialog-close]').forEach((button) => {
      button.addEventListener('click', () => closeDialog(dialog));
    });
  });
}());
