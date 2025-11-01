document.addEventListener('DOMContentLoaded', () => {
  const itemsGrid = document.getElementById('itemsGrid');
  if (itemsGrid) {
    const cards = Array.from(itemsGrid.querySelectorAll('[data-item]'));
    const searchInput = document.getElementById('searchItems');
    const statusButtons = document.querySelectorAll('[data-status-filter]');
    const emptyStateId = 'itemsGridEmptyState';
    let activeStatus = 'available';

    const ensureEmptyState = () => {
      let placeholder = document.getElementById(emptyStateId);
      if (!placeholder) {
        placeholder = document.createElement('div');
        placeholder.id = emptyStateId;
        placeholder.className = 'col-span-full rounded-3xl border border-dashed border-slate-300/80 bg-white/70 p-10 text-center text-sm text-slate-500 shadow-sm';
        placeholder.innerHTML = `
          <svg class="mx-auto mb-4 h-10 w-10 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M3 14s1-3 9-3 9 3 9 3" />
            <path d="M7 10a5 5 0 1 1 10 0" />
            <path d="M12 19h.01" />
          </svg>
          <p data-empty-message></p>
        `;
        placeholder.hidden = true;
        itemsGrid.appendChild(placeholder);
      }
      return placeholder;
    };

    const normalize = (value) => value.toLowerCase().trim();

    const updateGrid = () => {
      const query = normalize(searchInput?.value || '');
      const statusValue = activeStatus;
      let visibleCount = 0;

      cards.forEach((card) => {
        const name = normalize(card.getAttribute('data-name') || '');
        const location = normalize(card.getAttribute('data-location') || '');
        const description = normalize(card.getAttribute('data-description') || '');
        const status = (card.getAttribute('data-status') || 'available').toLowerCase();

        const matchesQuery = !query || name.includes(query) || location.includes(query) || description.includes(query);
        const matchesStatus = status === statusValue;
        const isVisible = matchesQuery && matchesStatus;

        card.classList.toggle('hidden', !isVisible);
        if (isVisible) visibleCount += 1;
      });

      const placeholder = ensureEmptyState();
      const messageEl = placeholder.querySelector('[data-empty-message]');
      if (messageEl) {
        messageEl.textContent = activeStatus === 'available'
          ? 'No items available'
          : 'No claimed items';
      }
      placeholder.hidden = visibleCount !== 0;
    };

    searchInput?.addEventListener('input', updateGrid);

    const setStatus = (status, { silent = false } = {}) => {
      if (!status) return;
      activeStatus = status;
      statusButtons.forEach((button) => {
        const buttonStatus = button.getAttribute('data-status-filter');
        const isActive = buttonStatus === status;
        button.classList.toggle('status-pill--active', isActive);
        button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
      });
      if (!silent) {
        updateGrid();
      }
    };

    statusButtons.forEach((button) => {
      button.addEventListener('click', () => {
        const nextStatus = button.getAttribute('data-status-filter');
        if (!nextStatus || nextStatus === activeStatus) {
          return;
        }
        setStatus(nextStatus);
      });
    });

    if (statusButtons.length > 0) {
      setStatus(activeStatus, { silent: true });
    }

    updateGrid();
  }

  const fileInput = document.getElementById('image');
  const previewWrapper = document.getElementById('imagePreviewContainer');
  const previewImage = document.getElementById('image-preview');
  const reportForm = document.getElementById('reportForm');

  if (fileInput && previewWrapper && previewImage) {
    let objectUrl = null;

    const revokeObjectUrl = () => {
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
        objectUrl = null;
      }
    };

    const resetPreview = () => {
      revokeObjectUrl();
      previewImage.removeAttribute('src');
      previewWrapper.hidden = true;
    };

    const updatePreview = () => {
      const file = fileInput.files?.[0];
      if (!file || !file.type.startsWith('image/')) {
        resetPreview();
        return;
      }

      revokeObjectUrl();
      objectUrl = URL.createObjectURL(file);
      previewImage.src = objectUrl;
      previewWrapper.hidden = false;
    };

    fileInput.addEventListener('change', updatePreview);
    fileInput.addEventListener('input', updatePreview);

    reportForm?.addEventListener('reset', () => {
      requestAnimationFrame(resetPreview);
    });
  }
});
