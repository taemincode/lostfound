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
        placeholder.className = 'col-span-full mx-auto max-w-2xl rounded-3xl border border-dashed border-slate-300/80 bg-white/70 p-10 text-center shadow-sm';
        placeholder.innerHTML = `
          <svg class="mx-auto h-12 w-12 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M3 14s1-3 9-3 9 3 9 3" />
            <path d="M7 10a5 5 0 1 1 10 0" />
            <path d="M12 19h.01" />
          </svg>
          <h2 class="mt-4 text-2xl font-semibold text-slate-900" data-empty-message></h2>
          <p class="mt-3 text-sm text-slate-500">Help your classmates by submitting a lost item report!</p>
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

  const MAX_IMAGE_BYTES = 3 * 1024 * 1024; // 3 MB
  const MAX_IMAGE_DIMENSION = 1600;
  const COMPRESSIBLE_TYPES = new Set(['image/jpeg', 'image/jpg', 'image/png', 'image/webp']);

  const fileInput = document.getElementById('image');
  const previewWrapper = document.getElementById('imagePreviewContainer');
  const previewImage = document.getElementById('image-preview');
  const sizeNote = document.getElementById('imageSizeNote');
  const reportForm = document.getElementById('reportForm');
  const submitButton = reportForm?.querySelector('[type="submit"]');

  if (fileInput && previewWrapper && previewImage) {
    let previewObjectUrl = null;
    let currentFileToken = 0;
    let isProcessingImage = false;
    let allowOversizedSubmission = false;

    const formatBytes = (bytes) => {
      if (!bytes || bytes <= 0) return '0 B';
      const units = ['B', 'KB', 'MB', 'GB'];
      const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
      const size = bytes / Math.pow(1024, exponent);
      return `${size.toFixed(exponent === 0 ? 0 : 1)} ${units[exponent]}`;
    };

    const revokePreviewUrl = () => {
      if (previewObjectUrl) {
        URL.revokeObjectURL(previewObjectUrl);
        previewObjectUrl = null;
      }
    };

    const clearPreview = () => {
      revokePreviewUrl();
      previewImage.removeAttribute('src');
      previewWrapper.hidden = true;
      allowOversizedSubmission = false;
      if (sizeNote) {
        sizeNote.hidden = true;
        sizeNote.textContent = '';
      }
    };

    const setPreview = (file, meta) => {
      revokePreviewUrl();
      previewObjectUrl = URL.createObjectURL(file);
      previewImage.src = previewObjectUrl;
      previewWrapper.hidden = false;

      if (sizeNote && meta) {
        const { wasCompressed, originalSize, finalSize } = meta;
        const finalText = `Final upload size: ${formatBytes(finalSize ?? file.size)}`;
        sizeNote.textContent = wasCompressed && originalSize
          ? `${finalText} (down from ${formatBytes(originalSize)})`
          : finalText;
        sizeNote.hidden = false;
      }
    };

    const readFileAsDataUrl = (file) =>
      new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(new Error('read-error'));
        reader.readAsDataURL(file);
      });

    const loadRenderableImage = async (file) => {
      if ('createImageBitmap' in window && typeof createImageBitmap === 'function') {
        try {
          const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
          return {
            width: bitmap.width,
            height: bitmap.height,
            draw: (ctx, width, height) => ctx.drawImage(bitmap, 0, 0, bitmap.width, bitmap.height, 0, 0, width, height),
            release: () => bitmap.close(),
          };
        } catch {
          // Fall back to Image tag path below
        }
      }

      const dataUrl = await readFileAsDataUrl(file);
      const image = new Image();
      image.decoding = 'async';
      const loadPromise = new Promise((resolve, reject) => {
        image.onload = () => resolve();
        image.onerror = () => reject(new Error('image-load-failed'));
      });
      image.src = dataUrl;
      await loadPromise;
      if (typeof image.decode === 'function') {
        try {
          await image.decode();
        } catch {
          // Ignore decode errors; onload already fired so we can still draw
        }
      }
      const width = image.naturalWidth || image.width;
      const height = image.naturalHeight || image.height;
      return {
        width,
        height,
        draw: (ctx, widthTarget, heightTarget) =>
          ctx.drawImage(image, 0, 0, width, height, 0, 0, widthTarget, heightTarget),
        release: () => {},
      };
    };

    const canvasToBlob = (canvas, mimeType, quality) =>
      new Promise((resolve, reject) => {
        if (typeof canvas.toBlob === 'function') {
          canvas.toBlob((blob) => {
            if (blob) {
              resolve(blob);
            } else {
              reject(new Error('blob-create-failed'));
            }
          }, mimeType, quality);
          return;
        }

        try {
          const dataUrl = canvas.toDataURL(mimeType, quality);
          fetch(dataUrl)
            .then((response) => response.blob())
            .then((blob) => {
              if (blob) {
                resolve(blob);
              } else {
                reject(new Error('blob-create-failed'));
              }
            })
            .catch(() => reject(new Error('blob-create-failed')));
        } catch {
          reject(new Error('blob-create-failed'));
        }
      });

    const prepareImageForUpload = async (file) => {
      const originalSize = file.size;
      const lowerType = (file.type || '').toLowerCase();
      if (!lowerType.startsWith('image/')) {
        return { file, wasCompressed: false, originalSize, finalSize: originalSize, allowOversized: false };
      }

      if (!COMPRESSIBLE_TYPES.has(lowerType)) {
        return {
          file,
          wasCompressed: false,
          originalSize,
          finalSize: originalSize,
          allowOversized: originalSize > MAX_IMAGE_BYTES,
        };
      }

      const renderable = await loadRenderableImage(file);
      try {
        let targetWidth = renderable.width;
        let targetHeight = renderable.height;
        const largestSide = Math.max(targetWidth, targetHeight);
        if (largestSide > MAX_IMAGE_DIMENSION) {
          const scale = MAX_IMAGE_DIMENSION / largestSide;
          targetWidth = Math.round(targetWidth * scale);
          targetHeight = Math.round(targetHeight * scale);
        }

        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d', { alpha: false });
        if (!ctx) {
          throw new Error('canvas-context');
        }
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = 'high';

        const drawToCanvas = () => {
          canvas.width = Math.max(1, Math.round(targetWidth));
          canvas.height = Math.max(1, Math.round(targetHeight));
          ctx.clearRect(0, 0, canvas.width, canvas.height);
          renderable.draw(ctx, canvas.width, canvas.height);
        };

        drawToCanvas();

        let quality = lowerType === 'image/png' ? 0.8 : 0.85;
        let blob = await canvasToBlob(canvas, 'image/jpeg', quality);
        let attempts = 0;

        while (blob.size > MAX_IMAGE_BYTES && attempts < 10) {
          if (quality > 0.55) {
            quality = Math.max(0.55, quality - 0.08);
          } else if (Math.max(targetWidth, targetHeight) > 640) {
            targetWidth = Math.max(Math.round(targetWidth * 0.85), 480);
            targetHeight = Math.max(Math.round(targetHeight * 0.85), 480);
            drawToCanvas();
          } else {
            break;
          }

          blob = await canvasToBlob(canvas, 'image/jpeg', quality);
          attempts += 1;
        }

        if (blob.size > MAX_IMAGE_BYTES) {
          throw new Error('image-too-large');
        }

        if (blob.size >= originalSize && attempts === 0) {
          return { file, wasCompressed: false, originalSize, finalSize: originalSize };
        }

        const baseName = file.name ? file.name.replace(/\.[^/.]+$/, '') : 'photo';
        const compressedFile = new File([blob], `${baseName || 'photo'}.jpg`, {
          type: 'image/jpeg',
          lastModified: Date.now(),
        });

        return {
          file: compressedFile,
          wasCompressed: true,
          originalSize,
          finalSize: compressedFile.size,
          allowOversized: false,
        };
      } finally {
        renderable.release();
      }
    };

    const assignFileToInput = (nextFile) => {
      try {
        if (typeof DataTransfer !== 'undefined') {
          const transfer = new DataTransfer();
          transfer.items.add(nextFile);
          fileInput.files = transfer.files;
          const assigned = fileInput.files?.[0];
          return Boolean(assigned && assigned.size === nextFile.size && assigned.name === nextFile.name);
        }
        if (typeof ClipboardEvent !== 'undefined') {
          const clipboard = new ClipboardEvent('').clipboardData;
          if (clipboard) {
            clipboard.items.add(nextFile);
            fileInput.files = clipboard.files;
            const assigned = fileInput.files?.[0];
            return Boolean(assigned && assigned.size === nextFile.size && assigned.name === nextFile.name);
          }
        }
      } catch (error) {
        console.warn('Unable to assign processed image file to the input element.', error);
      }
      return false;
    };

    const handleFileSelection = async () => {
      currentFileToken += 1;
      const token = currentFileToken;
      isProcessingImage = true;
      allowOversizedSubmission = false;
      if (submitButton) {
        submitButton.setAttribute('disabled', 'disabled');
        submitButton.setAttribute('data-loading', 'processing-image');
      }

      try {
        const file = fileInput.files?.[0];
        if (!file || !file.type.startsWith('image/')) {
          clearPreview();
          return;
        }

        const originalIsOversized = file.size > MAX_IMAGE_BYTES;
        const prepared = await prepareImageForUpload(file);
        if (token !== currentFileToken) {
          return;
        }

        let assigned = false;
        if (prepared.wasCompressed) {
          assigned = assignFileToInput(prepared.file);
        }

        if (prepared.allowOversized) {
          allowOversizedSubmission = true;
        }
        if (!allowOversizedSubmission && prepared.wasCompressed && originalIsOversized && !assigned) {
          allowOversizedSubmission = true;
        }

        const finalFile = assigned ? fileInput.files?.[0] ?? prepared.file : file;
        const meta = assigned
          ? prepared
          : { wasCompressed: false, originalSize: finalFile.size, finalSize: finalFile.size };

        setPreview(finalFile, meta);
      } catch (error) {
        if (token !== currentFileToken) {
          return;
        }

        console.error(error);
        allowOversizedSubmission = false;
        let message = 'We could not process this image. Please choose a different photo.';
        if (error.message === 'image-too-large') {
          message = 'We could not shrink this photo under 3 MB. Please choose a smaller image.';
        }
        alert(message);
        fileInput.value = '';
        clearPreview();
      } finally {
        if (token === currentFileToken) {
          isProcessingImage = false;
          submitButton?.removeAttribute('data-loading');
          submitButton?.removeAttribute('disabled');
        }
      }
    };

    fileInput.addEventListener('change', () => {
      void handleFileSelection();
    });

    reportForm?.addEventListener('reset', () => {
      currentFileToken += 1;
      requestAnimationFrame(() => {
        fileInput.value = '';
        clearPreview();
      });
    });

    reportForm?.addEventListener('submit', (event) => {
      if (isProcessingImage) {
        event.preventDefault();
        return;
      }
      const file = fileInput.files?.[0];
      if (!file) return;
      if (file.size > MAX_IMAGE_BYTES && !allowOversizedSubmission) {
        event.preventDefault();
        alert('Please choose a photo under 3 MB so we can process it quickly.');
      }
    });
  }
});
