(function () {
  const DEEP_LINK_DIALOG_IDS = new Set([
    'destination-dialog-seguridad',
    'destination-dialog-salud-emergencias',
  ]);
  const openers = document.querySelectorAll('[data-dialog-open]');
  if (typeof HTMLDialogElement === 'undefined') return;

  let activeTrigger = null;

  const focusDialog = (dialog) => {
    const focusable = dialog.querySelector('[data-dialog-close], button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    (focusable || dialog).focus();
  };

  const closeDialog = (dialog) => {
    if (!dialog || !dialog.open) return;
    dialog.close();
  };

  const openDialog = (dialog, trigger) => {
    if (!dialog || typeof dialog.showModal !== 'function' || dialog.open) return;
    if (trigger) activeTrigger = trigger;
    dialog.showModal();
    focusDialog(dialog);
  };

  openers.forEach((opener) => {
    opener.addEventListener('click', () => {
      const dialog = document.getElementById(opener.dataset.dialogOpen);
      openDialog(dialog, opener);
    });
  });

  const openDialogFromHash = () => {
    const id = window.location.hash.slice(1);
    if (!DEEP_LINK_DIALOG_IDS.has(id)) return;
    openDialog(document.getElementById(id), null);
  };

  document.querySelectorAll('a[href^="/#"]').forEach((link) => {
    const id = link.getAttribute('href').slice(2);
    if (!DEEP_LINK_DIALOG_IDS.has(id)) return;

    const dialog = document.getElementById(id);
    if (!dialog) return;

    link.addEventListener('click', (event) => {
      event.preventDefault();
      if (window.location.hash !== `#${id}`) window.location.hash = id;
      openDialog(dialog, link);
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

  openDialogFromHash();
  window.addEventListener('hashchange', openDialogFromHash);
}());
