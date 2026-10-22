



// ============================================================
// CLOCK
// ============================================================

function updateClock() {
    const now = new Date();
    const days = [
        'Sunday',
        'Monday',
        'Tuesday',
        'Wednesday',
        'Thursday',
        'Friday',
        'Saturday'
    ];

    const dayName = days[now.getDay()];
    const timeFormat = window.timeFormat || "12";

    let timeString;

    if (timeFormat === "24") {
        timeString = now.toLocaleTimeString('en-US', {
            hour12: false,
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    } else {
        timeString = now.toLocaleTimeString('en-US', {
            hour12: true,
            hour: 'numeric',
            minute: '2-digit',
            second: '2-digit'
        });
    }

    const dateTimeElement = document.getElementById('currentDateTime');

    if (dateTimeElement) {
        dateTimeElement.textContent = `${dayName} ${timeString}`;
    }
}

updateClock();
setInterval(updateClock, 1000);






// ============================================================
// TOM SELECT
// ============================================================

document.querySelectorAll(".tomselect-single").forEach(el => {
    const select = new TomSelect(el, {
        create: false,
        maxItems: 1,
        placeholder: "Select Tag"
    });
    if (el.disabled) select.disable();
    else select.enable();
});

document.querySelectorAll(".tomselect").forEach(el => {
    new TomSelect(el, {
        plugins: ['remove_button'],
        placeholder: 'Select Tag',
        maxItems: null
    });
});

// ============================================================
// DOM READY
// ============================================================

document.addEventListener('DOMContentLoaded', () => {

    // Submit tag-management forms without navigating away, so the modal stays open.
    async function handleTagFormSubmit(event) {
        if (event.defaultPrevented) return; // Respect delete confirmation prompts.

        event.preventDefault();
        const form = event.currentTarget;
        const modal = form.closest('.modal');
        if (!modal) return;

        form.querySelectorAll('button[type="submit"], button:not([type])').forEach(button => {
            button.disabled = true;
        });

        // Give visible feedback while tags are being pushed to secondary Pis.
        if (form.id === 'syncTagsForm') {
            const spinner = document.getElementById('syncTagsSpinner');
            const icon = document.getElementById('syncTagsIcon');
            const buttonText = document.getElementById('syncTagsButtonText');
            const progress = document.getElementById('syncTagsProgress');

            spinner?.classList.remove('d-none');
            icon?.classList.add('d-none');
            if (buttonText) buttonText.textContent = 'Syncing Tags...';
            progress?.classList.remove('d-none');
        }

        try {
            const response = await fetch(form.action, {
                method: (form.method || 'POST').toUpperCase(),
                body: new FormData(form),
                credentials: 'same-origin',
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            if (!response.ok) throw new Error(`Request failed (${response.status})`);

            if (form.id === 'syncTagsForm') {
                const data = await response.json();
                const spinner = document.getElementById('syncTagsSpinner');
                const icon = document.getElementById('syncTagsIcon');
                const buttonText = document.getElementById('syncTagsButtonText');
                const progress = document.getElementById('syncTagsProgress');
                const resultContainer = document.getElementById('syncTagsResult');
                const syncButton = document.getElementById('syncTagsSubmitBtn');

                spinner?.classList.add('d-none');
                icon?.classList.remove('d-none');
                progress?.classList.add('d-none');
                if (syncButton) syncButton.disabled = false;
                if (buttonText) buttonText.textContent = 'Sync Tags to Secondaries';

                if (resultContainer) {
                    resultContainer.className = `mt-3 alert ${data.success ? 'alert-success' : 'alert-warning'}`;
                    resultContainer.replaceChildren();

                    const heading = document.createElement('div');
                    heading.className = 'fw-semibold mb-2';
                    heading.textContent = data.message || 'Sync completed.';
                    resultContainer.appendChild(heading);

                    (data.results || []).forEach(item => {
                        const row = document.createElement('div');
                        row.className = item.success ? 'text-success' : 'text-danger';
                        row.textContent = `${item.name}${item.ip ? ' — ' + item.ip : ''}: ${item.message}`;
                        resultContainer.appendChild(row);
                    });
                    resultContainer.classList.remove('d-none');
                }
                return;
            }

            const data = await response.json();
            if (!data.success) throw new Error(data.error || 'Unable to update tags.');

            const isSchedule = modal.id === 'scheduleTagsModal';
            const list = modal.querySelector('.border.rounded:not(.text-center)');
            const emptyState = modal.querySelector('.border.rounded.text-center');
            const isDelete = form.action.includes('delete_');

            if (isDelete) {
                const row = form.closest('.d-flex.align-items-center.justify-content-between');
                row?.remove();
                const remainingRows = modal.querySelectorAll('.border.rounded:not(.text-center) > .d-flex.align-items-center.justify-content-between');
                if (!remainingRows.length) {
                    const currentList = modal.querySelector('.border.rounded:not(.text-center)');
                    currentList?.remove();
                    const empty = document.createElement('div');
                    empty.className = 'border rounded text-center text-muted p-3';
                    empty.textContent = isSchedule ? 'No Schedule Tags have been created yet.' : 'No Sync Tags have been created yet.';
                    modal.querySelector('.card-body')?.appendChild(empty);
                }
            } else {
                const tag = data.tag;
                if (tag) {
                    const row = document.createElement('div');
                    row.className = 'd-flex align-items-center justify-content-between px-3 py-2 border-bottom';
                    const info = document.createElement('div');
                    info.className = 'd-flex align-items-center';
                    const icon = document.createElement('i');
                    icon.className = isSchedule ? 'bi bi-tag text-primary me-2' : 'bi bi-link-45deg text-primary me-2';
                    info.appendChild(icon);
                    const label = document.createElement('span');
                    label.className = 'fw-semibold me-3';
                    label.textContent = isSchedule ? tag.name : tag;
                    info.appendChild(label);
                    const count = document.createElement('span');
                    count.className = 'text-muted small';
                    count.textContent = 'Not assigned';
                    info.appendChild(count);
                    row.appendChild(info);

                    const deleteForm = document.createElement('form');
                    deleteForm.method = 'POST';
                    deleteForm.action = isSchedule ? '/delete_schedule_tag' : '/delete_sync_tag';
                    deleteForm.addEventListener('submit', event => {
                        if (!confirm(isSchedule
                            ? 'Delete Schedule Tag ' + tag.name + '?'
                            : 'Delete Sync Tag ' + tag + '? Any video using this tag will be cleared.')) {
                            event.preventDefault();
                        }
                    });
                    const hidden = document.createElement('input');
                    hidden.type = 'hidden';
                    hidden.name = isSchedule ? 'schedule_tag' : 'sync_tag';
                    hidden.value = isSchedule ? tag.id : tag;
                    deleteForm.appendChild(hidden);
                    const deleteButton = document.createElement('button');
                    deleteButton.type = 'submit';
                    deleteButton.className = 'btn btn-outline-danger btn-sm';
                    deleteButton.textContent = 'Delete';
                    deleteForm.appendChild(deleteButton);
                    row.appendChild(deleteForm);

                    let targetList = list;
                    if (!targetList) {
                        emptyState?.remove();
                        targetList = document.createElement('div');
                        targetList.className = 'border rounded';
                        modal.querySelector('.card-body')?.appendChild(targetList);
                    }
                    targetList.appendChild(row);
                    bindTagForms(modal);
                    const addInput = modal.querySelector('input[name="' + (isSchedule ? 'schedule_tag' : 'sync_tag') + '"]');
                    if (addInput) addInput.value = '';
                }
            }

            const currentTags = data.tags || [];
            document.querySelectorAll('select').forEach(select => {
                const selectorName = (select.name || '') + ' ' + (select.id || '');
                if (isSchedule) {
                    if (!/tag|category/i.test(selectorName) || /sync/i.test(selectorName)) return;
                } else if (!/sync/i.test(selectorName)) {
                    return;
                }
                const selected = Array.from(select.selectedOptions).map(option => option.value);
                const values = isSchedule
                    ? currentTags.map(tag => ({ value: tag.id, label: tag.name }))
                    : currentTags.map(tag => ({ value: tag, label: tag }));
                const placeholder = select.querySelector('option[value=""]');
                const emptyOption = placeholder ? placeholder.cloneNode(true) : null;
                select.replaceChildren();
                if (emptyOption) select.appendChild(emptyOption);
                values.forEach(item => {
                    const option = document.createElement('option');
                    option.value = item.value;
                    option.textContent = item.label;
                    option.selected = selected.includes(item.value);
                    select.appendChild(option);
                });
            });

            if (typeof showToast === 'function') showToast(data.message || 'Tags updated.', 'success');
        } catch (error) {
            console.error('Unable to update tags:', error);
            window.location.reload();
        }
    }

    function bindTagForms(container) {
        if (!container) return;
        container.querySelectorAll('form').forEach(form => {
            if (form.dataset.ajaxTagFormBound === 'true') return;
            form.dataset.ajaxTagFormBound = 'true';
            form.addEventListener('submit', handleTagFormSubmit);
        });
    }

    bindTagForms(document.getElementById('scheduleTagsModal'));
    bindTagForms(document.getElementById('syncTagsModal'));

    // FILE UPLOAD
    // ========================================================

    const dropArea = document.getElementById('dropArea');
    const fileInput = document.getElementById('fileInput');
    const fileName = document.getElementById('fileName');
    const uploadBtn = document.getElementById('uploadBtn');
    const days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'];
    const triggerToggle = document.getElementById("triggeredFlag");
    const delayDropdown = document.getElementById("delay");

// ========================================================
// BOOTSTRAP VALIDATION MODAL
// ========================================================

const validationModalElement = document.getElementById('validationModal');
const validationModal = validationModalElement
    ? bootstrap.Modal.getOrCreateInstance(validationModalElement)
    : null;

const modalBody = document.getElementById('validationModalBody');

const copyScheduleModalElement =
    document.getElementById('copyScheduleModal');

const copyScheduleModal = copyScheduleModalElement
    ? bootstrap.Modal.getOrCreateInstance(copyScheduleModalElement)
    : null;

    // ========================================================
    // LOG VIEWER
    // ========================================================

    const logList = document.getElementById('log');
    const logDetails = document.getElementById('log_details');
    const logContent = document.getElementById('logContent');
    const backBtn = document.getElementById('backToList');
    const detailSearch = document.getElementById('detailSearch');
    const detailCategory = document.getElementById('detailCategory');
    const clearDetailFilters = document.getElementById('clearDetailFilters');
    const detailFilterCount = document.getElementById('detailFilterCount');

    let currentLogContent = '';

    function filterLogContent() {
        if (!logContent) return;

        const searchText = detailSearch
            ? detailSearch.value.trim().toLowerCase()
            : '';

        const category = detailCategory
            ? detailCategory.value
            : 'ALL';

        const lines = currentLogContent.split('\n');

        const filteredLines = lines.filter(line => {
            if (!line.trim()) return false;

            if (category !== 'ALL') {
                const categoryMatch = line.match(/^\[[^\]]+\]\s+\[([^\]]+)\]/);

                if (!categoryMatch ||
                    categoryMatch[1].toUpperCase() !== category.toUpperCase()) {
                    return false;
                }
            }

            if (searchText && !line.toLowerCase().includes(searchText)) {
                return false;
            }

            return true;
        });

        logContent.textContent = filteredLines.join('\n');

        if (detailFilterCount) {
            detailFilterCount.textContent =
                `${filteredLines.length} of ${lines.filter(line => line.trim()).length} entries`;
        }
    }

    document.querySelectorAll('.view-log').forEach(link => {
        link.addEventListener('click', async e => {
            e.preventDefault();

            const filename = e.target.dataset.filename;

            try {
                const response = await fetch(`/logs/raw/${filename}`);

                if (!response.ok) {
                    throw new Error("Log not found");
                }

                currentLogContent = await response.text();

                if (detailSearch) {
                    detailSearch.value = '';
                }

                if (detailCategory) {
                    detailCategory.value = 'ALL';
                }

                filterLogContent();

                logList.classList.add('d-none');
                logDetails.classList.remove('d-none');
            } catch (err) {
                currentLogContent = '';
                logContent.textContent = 'Error loading log: ' + err.message;

                if (detailFilterCount) {
                    detailFilterCount.textContent = '';
                }

                logList.classList.add('d-none');
                logDetails.classList.remove('d-none');
            }
        });
    });

    if (detailSearch) {
        detailSearch.addEventListener('input', filterLogContent);
    }

    if (detailCategory) {
        detailCategory.addEventListener('change', filterLogContent);
    }

    if (clearDetailFilters) {
        clearDetailFilters.addEventListener('click', () => {
            if (detailSearch) {
                detailSearch.value = '';
            }

            if (detailCategory) {
                detailCategory.value = 'ALL';
            }

            filterLogContent();
        });
    }

    if (backBtn) {
        backBtn.addEventListener('click', () => {
            logDetails.classList.add('d-none');
            logList.classList.remove('d-none');
            logContent.textContent = '';
            currentLogContent = '';

            if (detailSearch) {
                detailSearch.value = '';
            }

            if (detailCategory) {
                detailCategory.value = 'ALL';
            }

            if (detailFilterCount) {
                detailFilterCount.textContent = '';
            }
        });
    }

    // ========================================================
    // TRIGGER DELAY
    // ========================================================

    function updateDelayState() {
        if (delayDropdown && triggerToggle) {
            delayDropdown.disabled = !triggerToggle.checked;
        }
    }

    if (triggerToggle && delayDropdown) {
        triggerToggle.addEventListener("change", updateDelayState);
        updateDelayState();
    }

    /// ========================================================
    // SCHEDULE SLOT VALIDATION
    // ========================================================

    const slots = ['Slot1', 'Slot2'];
    const allSlotValidators = [];

    days.forEach(day => {
        const slotElements = slots.map(slot => ({
            toggle: document.getElementById(`${day}${slot}Enabled`),
            start: document.getElementById(`${day}${slot}Start`),
            end: document.getElementById(`${day}${slot}End`),
            category: document.getElementById(`${day}${slot}Category`)
        }));

        slotElements.forEach((slotObj, idx) => {
            if (!slotObj.toggle || !slotObj.start || !slotObj.end) return;

            const updateSlotInputs = () => {
                const enabled = slotObj.toggle.checked;
                slotObj.start.disabled = !enabled;
                slotObj.end.disabled = !enabled;
                if (slotObj.category) {
                    slotObj.category.disabled = !enabled;
                }
            };

            updateSlotInputs();
            slotObj.toggle.addEventListener('change', updateSlotInputs);

            const validateTimes = () => {
                if (!slotObj.toggle.checked) {
                    return true;
                }

                if (!slotObj.start.value || !slotObj.end.value) {
                    if (modalBody && validationModal) {
                        modalBody.textContent =
                            `On ${day.charAt(0).toUpperCase() + day.slice(1)} (${slots[idx]}), both start and end times must be filled.`;
                        validationModal.show();
                    }
                    slotObj.start.focus();
                    return false;
                }

                if (slotObj.start.value >= slotObj.end.value) {
                    if (modalBody && validationModal) {
                        modalBody.textContent =
                            `On ${day.charAt(0).toUpperCase() + day.slice(1)} (${slots[idx]}), start time must be before end time.`;
                        validationModal.show();
                    }
                    slotObj.start.focus();
                    return false;
                }

                for (let otherIdx = 0; otherIdx < slotElements.length; otherIdx++) {
                    if (otherIdx === idx) continue;

                    const other = slotElements[otherIdx];

                    if (!other.toggle ||
                        !other.toggle.checked ||
                        !other.start.value ||
                        !other.end.value) {
                        continue;
                    }

                    if (!(slotObj.end.value <= other.start.value ||
                        slotObj.start.value >= other.end.value)) {
                        if (modalBody && validationModal) {
                            modalBody.textContent =
                                `On ${day.charAt(0).toUpperCase() + day.slice(1)}, ${slots[idx]} overlaps with ${slots[otherIdx]}.`;
                            validationModal.show();
                        }
                        slotObj.start.focus();
                        return false;
                    }
                }

                return true;
            };

            allSlotValidators.push(validateTimes);
            slotObj.start.addEventListener('blur', validateTimes);
            slotObj.end.addEventListener('blur', validateTimes);
            slotObj.toggle.addEventListener('change', validateTimes);
        });
    });


    // ========================================================
// COPY SCHEDULE SETTINGS TO ALL DAYS
// ========================================================

document.querySelectorAll('.copy-to-all-btn').forEach(button => {
    button.addEventListener('click', () => {
        const sourceDay = button.dataset.day;

        const sourceSlot1Enabled =
            document.getElementById(`${sourceDay}Slot1Enabled`);
        const sourceSlot1Start =
            document.getElementById(`${sourceDay}Slot1Start`);
        const sourceSlot1End =
            document.getElementById(`${sourceDay}Slot1End`);
        const sourceSlot1Category =
            document.getElementById(`${sourceDay}Slot1Category`);

        const sourceSlot2Enabled =
            document.getElementById(`${sourceDay}Slot2Enabled`);
        const sourceSlot2Start =
            document.getElementById(`${sourceDay}Slot2Start`);
        const sourceSlot2End =
            document.getElementById(`${sourceDay}Slot2End`);
        const sourceSlot2Category =
            document.getElementById(`${sourceDay}Slot2Category`);

        days.forEach(day => {
            if (day === sourceDay) {
                return;
            }

            const slot1Enabled =
                document.getElementById(`${day}Slot1Enabled`);
            const slot1Start =
                document.getElementById(`${day}Slot1Start`);
            const slot1End =
                document.getElementById(`${day}Slot1End`);
            const slot1Category =
                document.getElementById(`${day}Slot1Category`);

            const slot2Enabled =
                document.getElementById(`${day}Slot2Enabled`);
            const slot2Start =
                document.getElementById(`${day}Slot2Start`);
            const slot2End =
                document.getElementById(`${day}Slot2End`);
            const slot2Category =
                document.getElementById(`${day}Slot2Category`);

            // Copy all values first.
            // Do NOT dispatch change events until everything is copied.

            // SLOT 1
            if (slot1Enabled && sourceSlot1Enabled) {
                slot1Enabled.checked = sourceSlot1Enabled.checked;
            }

            if (slot1Start && sourceSlot1Start) {
                slot1Start.value = sourceSlot1Start.value;
            }

            if (slot1End && sourceSlot1End) {
                slot1End.value = sourceSlot1End.value;
            }

            if (slot1Category && sourceSlot1Category) {
                slot1Category.value = sourceSlot1Category.value;
            }

            // SLOT 2
            if (slot2Enabled && sourceSlot2Enabled) {
                slot2Enabled.checked = sourceSlot2Enabled.checked;
            }

            if (slot2Start && sourceSlot2Start) {
                slot2Start.value = sourceSlot2Start.value;
            }

            if (slot2End && sourceSlot2End) {
                slot2End.value = sourceSlot2End.value;
            }

            if (slot2Category && sourceSlot2Category) {
                slot2Category.value = sourceSlot2Category.value;
            }

            // Update enabled/disabled state only after all values are copied.
            if (slot1Enabled) {
                slot1Enabled.dispatchEvent(new Event('change'));
            }

            if (slot2Enabled) {
                slot2Enabled.dispatchEvent(new Event('change'));
            }
        });

        if (copyScheduleModal) {
            copyScheduleModal.show();
        }
    });
});
 

    // ========================================================
    // SCHEDULE FORM VALIDATION
    // ========================================================

    const scheduleForm = document.getElementById('scheduleForm');

    if (scheduleForm) {
        scheduleForm.addEventListener('submit', e => {
            for (const validate of allSlotValidators) {
                if (!validate()) {
                    e.preventDefault();
                    return false;
                }
            }
        });
    }

    // ========================================================
    // UPLOAD FORM
    // ========================================================

    const uploadForm = document.getElementById('uploadForm');

    if (uploadForm) {
        uploadForm.addEventListener('submit', async event => {
            if (event.defaultPrevented) return;
            event.preventDefault();

            const overlay = document.getElementById('loadingOverlay');
            const errorBox = document.getElementById('uploadError');
            const uploadButton = document.getElementById('uploadBtn');
            const fileInput = document.getElementById('fileInput');
            if (!fileInput || !fileInput.files.length) return;

            if (overlay) overlay.style.display = 'flex';
            if (errorBox) {
                errorBox.classList.add('d-none');
                errorBox.classList.remove('alert-success');
                errorBox.classList.add('alert-danger');
                errorBox.textContent = '';
            }
            if (uploadButton) uploadButton.disabled = true;

            try {
                const response = await fetch(uploadForm.action, {
                    method: 'POST',
                    body: new FormData(uploadForm),
                    credentials: 'same-origin',
                    headers: { 'X-Requested-With': 'XMLHttpRequest' }
                });
                const data = await response.json();
                if (!response.ok || !data.success) {
                    throw new Error(data.error || (data.errors || []).join('\n') || 'Upload failed.');
                }

                if (overlay) overlay.style.display = 'none';
                if (errorBox) {
                    errorBox.classList.remove('d-none', 'alert-danger');
                    errorBox.classList.add('alert-success');
                    errorBox.textContent = 'Uploaded: ' + (data.uploaded || []).join(', ') + '. Close this window to refresh the video list.';
                }
                const cancelButton = uploadForm.querySelector('[data-bs-dismiss="modal"]');
                if (cancelButton) cancelButton.textContent = 'Close & Refresh';
                const modalElement = document.getElementById('uploadModal');
                if (modalElement) {
                    modalElement.addEventListener('hidden.bs.modal', () => window.location.reload(), { once: true });
                }
                if (uploadButton) {
                    uploadButton.disabled = true;
                    uploadButton.innerHTML = '<i class="bi bi-check-circle me-1"></i> Uploaded';
                }
            } catch (error) {
                if (overlay) overlay.style.display = 'none';
                if (errorBox) {
                    errorBox.classList.remove('d-none');
                    errorBox.textContent = error.message || 'Upload failed.';
                } else {
                    window.alert(error.message || 'Upload failed.');
                }
                if (uploadButton) uploadButton.disabled = false;
            }
        });
    }

    // ========================================================
    // NETWORK SETTINGS
    // ========================================================

    const networkForm = document.getElementById('networkForm');
    const networkLoading = document.getElementById('networkLoading');

    if (networkForm && networkLoading) {
        networkForm.addEventListener('submit', () => {
            networkLoading.style.display = 'flex';
        });
    }

    // ========================================================
    // SYNC TAGS
    // ========================================================

    const syncTagsForm = document.getElementById('syncTagsForm');
    const syncTagsLoading = document.getElementById('syncTagsLoading');

    if (syncTagsForm && syncTagsLoading) {
        syncTagsForm.addEventListener('submit', () => {
            syncTagsLoading.style.display = 'flex';
        });
    }

    // ========================================================
    // DRAG & DROP UPLOAD
    // ========================================================

    if (dropArea && fileInput) {
        const chooseFilesBtn = document.getElementById('chooseFilesBtn');
        const uploadError = document.getElementById('uploadError');

        if (chooseFilesBtn) {
            chooseFilesBtn.addEventListener('click', () => fileInput.click());
        }

        ['dragenter', 'dragover'].forEach(eventName => {
            dropArea.addEventListener(eventName, event => {
                event.preventDefault();
                event.stopPropagation();
                dropArea.classList.add('border-primary', 'bg-light');
            });
        });

        ['dragleave', 'drop'].forEach(eventName => {
            dropArea.addEventListener(eventName, event => {
                event.preventDefault();
                event.stopPropagation();
                dropArea.classList.remove('border-primary', 'bg-light');
            });
        });

        dropArea.addEventListener('drop', event => {
            setSelectedFiles(Array.from(event.dataTransfer.files));
        });

        fileInput.addEventListener('change', () => {
            setSelectedFiles(Array.from(fileInput.files));
        });

        function setSelectedFiles(files) {
            const validFiles = files.filter(file =>
                file.name.toLowerCase().endsWith('.mp4') &&
                (!file.type || file.type === 'video/mp4' || file.type === 'application/octet-stream')
            );

            if (uploadError) {
                uploadError.textContent = '';
                uploadError.classList.add('d-none');
            }

            if (validFiles.length !== files.length || files.length === 0) {
                if (uploadError) {
                    uploadError.textContent = 'Please select one or more valid MP4 files.';
                    uploadError.classList.remove('d-none');
                }
                uploadBtn.disabled = true;
                fileName.textContent = '';
                fileInput.value = '';
                return;
            }

            const transfer = new DataTransfer();
            validFiles.forEach(file => transfer.items.add(file));
            fileInput.files = transfer.files;

            fileName.replaceChildren();
            const list = document.createElement('ul');
            list.className = 'list-group list-group-flush';
            validFiles.forEach(file => {
                const item = document.createElement('li');
                item.className = 'list-group-item px-0';
                item.dataset.uploadRow = 'true';
                item.dataset.filename = file.name;

                const top = document.createElement('div');
                top.className = 'd-flex justify-content-between align-items-center gap-3 mb-2';
                const name = document.createElement('span');
                name.className = 'text-break fw-medium';
                name.textContent = file.name;
                const size = document.createElement('span');
                size.className = 'text-muted small text-nowrap';
                size.textContent = (file.size / (1024 * 1024)).toFixed(1) + ' MB';
                top.append(name, size);

                const bottom = document.createElement('div');
                bottom.className = 'd-flex align-items-center gap-2';
                const progress = document.createElement('div');
                progress.className = 'progress upload-file-progress flex-grow-1';
                progress.setAttribute('role', 'progressbar');
                progress.setAttribute('aria-label', 'Upload progress for ' + file.name);
                progress.setAttribute('aria-valuemin', '0');
                progress.setAttribute('aria-valuemax', '100');
                progress.setAttribute('aria-valuenow', '0');
                const bar = document.createElement('div');
                bar.className = 'progress-bar';
                bar.style.width = '0%';
                progress.appendChild(bar);
                const status = document.createElement('span');
                status.className = 'upload-file-status small text-muted text-nowrap';
                status.textContent = 'Waiting';
                bottom.append(progress, status);
                item.append(top, bottom);
                list.appendChild(item);
            });
            fileName.appendChild(list);
            uploadBtn.disabled = false;
        }

        const uploadForm = document.getElementById('uploadForm');
        if (uploadForm) {
            uploadForm.addEventListener('submit', async event => {
                event.preventDefault();
                const files = Array.from(fileInput.files);
                if (!files.length) return;

                uploadBtn.disabled = true;
                const originalButton = uploadBtn.innerHTML;
                uploadBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Uploading...';
                if (uploadError) {
                    uploadError.classList.add('d-none');
                    uploadError.textContent = '';
                }

                const rows = Array.from(fileName.querySelectorAll('[data-upload-row]'));
                let completed = 0;
                let failed = 0;

                const uploadOne = file => new Promise(resolve => {
                    const row = rows.find(element => element.dataset.filename === file.name);
                    const progress = row?.querySelector('.upload-file-progress');
                    const status = row?.querySelector('.upload-file-status');
                    const bar = row?.querySelector('.progress-bar');
                    const formData = new FormData();
                    formData.append('file', file, file.name);

                    const csrf = uploadForm.querySelector('input[name="csrf_token"]');
                    if (csrf) formData.append('csrf_token', csrf.value);

                    const xhr = new XMLHttpRequest();
                    xhr.open('POST', uploadForm.action);
                    xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');

                    xhr.upload.addEventListener('progress', event => {
                        if (!event.lengthComputable || !bar || !status) return;
                        const percent = Math.min(100, Math.round((event.loaded / event.total) * 100));
                        bar.style.width = percent + '%';
                        bar.setAttribute('aria-valuenow', String(percent));
                        status.textContent = percent + '%';
                    });

                    xhr.addEventListener('load', () => {
                        let result = {};
                        try { result = JSON.parse(xhr.responseText); } catch (_) {}
                        if (xhr.status >= 200 && xhr.status < 300 && result.success) {
                            completed++;
                            if (bar) {
                                bar.style.width = '100%';
                                bar.classList.add('bg-success');
                            }
                            if (status) status.textContent = 'Complete';
                            if (progress) progress.classList.add('upload-complete');
                            resolve({ success: true, file });
                        } else {
                            failed++;
                            if (bar) bar.classList.add('bg-danger');
                            if (status) status.textContent = 'Failed';
                            resolve({ success: false, file, error: result.error || 'Server rejected the upload.' });
                        }
                    });

                    xhr.addEventListener('error', () => {
                        failed++;
                        if (bar) bar.classList.add('bg-danger');
                        if (status) status.textContent = 'Network error';
                        resolve({ success: false, file, error: 'Network error while uploading ' + file.name });
                    });

                    xhr.send(formData);
                });

                // Upload files one at a time so each file has its own accurate progress bar.
                const results = [];
                for (const file of files) {
                    const row = rows.find(element => element.dataset.filename === file.name);
                    const status = row?.querySelector('.upload-file-status');
                    if (status) status.textContent = 'Uploading…';
                    results.push(await uploadOne(file));
                }

                if (failed === 0) {
                    if (uploadError) {
                        uploadError.className = 'alert alert-success mt-3 mb-0';
                        uploadError.textContent = 'Successfully uploaded ' + completed + ' video(s). Refreshing the video library…';
                    }
                    window.location.reload();
                } else {
                    if (uploadError) {
                        uploadError.className = 'alert alert-danger mt-3 mb-0';
                        uploadError.textContent = completed + ' uploaded; ' + failed + ' failed. Failed files are marked below. Close this dialog and select those files again to retry.';
                    }
                    uploadBtn.disabled = false;
                    uploadBtn.innerHTML = originalButton;
                    fileInput.value = '';
                }
            });
        }


// ========================================================
// PLAYLIST MODE
// ========================================================

const modeSelect = document.getElementById('modeSelect');
const intervalGroup = document.getElementById('intervalGroup');
const intervalSelect = document.getElementById('interval');
const singleVideoGroup = document.getElementById('singleVideoSelectGroup');
const fixedPlaylistGroup = document.getElementById('fixedPlaylistGroup');
const secondaryVideoMode = document.getElementById('secondaryVideoMode');
const triggerChangeGroup = document.getElementById('triggerChangeGroup');
const triggerChange = document.getElementById('triggerChange');

function updateModeUI() {
    if (!modeSelect) return;

    const isSecondary = !!secondaryVideoMode;
    const isSyncTag = isSecondary && secondaryVideoMode.value === 'sync_tag';
    const isSecondaryPlaylist = isSecondary && secondaryVideoMode.value === 'playlist';

    const singleOption = modeSelect.querySelector('option[value="single"]');
    const randomOption = modeSelect.querySelector('option[value="random"]');
    const fixedOption = modeSelect.querySelector('option[value="fixed"]');

    if (isSyncTag) {
        if (singleOption) singleOption.disabled = false;
        if (randomOption) randomOption.disabled = true;
        if (fixedOption) fixedOption.disabled = true;

        modeSelect.value = 'single';
    } else if (isSecondaryPlaylist) {
        if (singleOption) singleOption.disabled = true;
        if (randomOption) randomOption.disabled = modeSelect.dataset.videoCount < 2;
        if (fixedOption) fixedOption.disabled = modeSelect.dataset.videoCount < 2;

        if (modeSelect.value === 'single' || modeSelect.value === '') {
            modeSelect.value = 'random';
        }
    } else {
        if (singleOption) singleOption.disabled = false;
        if (randomOption) randomOption.disabled = modeSelect.dataset.videoCount < 2;
        if (fixedOption) fixedOption.disabled = modeSelect.dataset.videoCount < 2;
    }

    const currentMode = modeSelect.value;
    const supportsTriggerChange = currentMode === 'random' || currentMode === 'fixed';

    if (triggerChangeGroup) {
        triggerChangeGroup.style.display = supportsTriggerChange ? 'flex' : 'none';
    }

    if (!supportsTriggerChange && triggerChange) {
        triggerChange.checked = false;
    }

    if (supportsTriggerChange && triggerChange && triggerChange.checked) {
        if (intervalGroup) {
            intervalGroup.style.display = 'none';
        }

        if (intervalSelect) {
            intervalSelect.disabled = true;
        }
    } else if (currentMode === 'random' || currentMode === 'fixed') {
        if (intervalGroup) {
            intervalGroup.style.display = 'block';
        }

        if (intervalSelect) {
            intervalSelect.disabled = false;
        }
    } else {
        if (intervalGroup) {
            intervalGroup.style.display = 'none';
        }

        if (intervalSelect) {
            intervalSelect.disabled = true;
        }
    }

    if (singleVideoGroup) {
        if (!isSecondary && currentMode === 'single') {
            singleVideoGroup.style.display = 'block';
        } else {
            singleVideoGroup.style.display = 'none';
        }
    }

    if (fixedPlaylistGroup) {
        fixedPlaylistGroup.style.display =
            currentMode === 'fixed' ? 'block' : 'none';
    }
}

if (modeSelect) {
    modeSelect.dataset.videoCount = '{{ video_count }}';
    modeSelect.addEventListener('change', updateModeUI);
}

if (secondaryVideoMode) {
    secondaryVideoMode.addEventListener('change', updateModeUI);
}

if (triggerChange) {
    triggerChange.addEventListener('change', updateModeUI);
}

updateModeUI();
 




    // ========================================================
    // VIDEO PREVIEW
    // ========================================================

    const videoSelect = document.getElementById('video');
    const videoPreview = document.getElementById('videoPreview');

    function updateVideoPreview() {
        if (!videoSelect || !videoPreview) return;

        const video = videoSelect.value;

        if (video) {
            videoPreview.src = `/videos/${encodeURIComponent(video)}`;
            videoPreview.load();
        } else {
            videoPreview.pause();
            videoPreview.src = '';
        }
    }

    if (videoSelect) {
        videoSelect.addEventListener('change', updateVideoPreview);
        updateVideoPreview();
    }

// ========================================================
// MANAGE VIDEO TABS
// ========================================================

const manageTabs = document.querySelectorAll('#manageTabs button[data-bs-toggle="tab"]');

manageTabs.forEach(tab => {
    tab.addEventListener('shown.bs.tab', event => {
        localStorage.setItem(
            'activeManageTab',
            event.target.getAttribute('data-bs-target')
        );
    });
});

const savedManageTab = localStorage.getItem('activeManageTab');

if (savedManageTab) {
    const savedTab = document.querySelector(
        `#manageTabs button[data-bs-target="${savedManageTab}"]`
    );

    if (savedTab) {
        bootstrap.Tab.getOrCreateInstance(savedTab).show();
    }
}


// ========================================================
// FIXED PLAYLIST REORDERING
// ========================================================

const fixedPlaylist = document.getElementById('fixedPlaylist');
const fixedOrderInput = document.getElementById('fixedOrderInput');

if (fixedPlaylist && fixedOrderInput) {
    Sortable.create(fixedPlaylist, {
        animation: 150,
        onEnd: () => {
            const order = Array.from(fixedPlaylist.querySelectorAll('li'))
                .map(li => li.dataset.filename);
            fixedOrderInput.value = order.join(',');
        }
    });

    const initialOrder = Array.from(fixedPlaylist.querySelectorAll('li'))
        .map(li => li.dataset.filename);

    fixedOrderInput.value = initialOrder.join(',');
}

    // ========================================================
    // COUNTDOWN TIMER
    // ========================================================

    if (window.countdownConfig && window.countdownConfig.enabled) {
        let countdown = window.countdownConfig.timeRemaining;
        const countdownElement = document.getElementById('countdown');

        if (countdownElement) {
            const countdownInterval = setInterval(() => {
                if (--countdown >= 0) {
                    countdownElement.textContent = countdown;
                } else {
                    clearInterval(countdownInterval);
                    location.reload();
                }
            }, 1500);
        }
    }


    // ========================================================
    // SIDEBAR NAVIGATION
    // ========================================================

    const navLinks = document.querySelectorAll('.sidebar .nav-link');
    const sections = document.querySelectorAll('.section');
    const sidebar = document.getElementById('sidebar');
    const content = document.getElementById('mainContent');
    const toggleButton = document.getElementById('toggleSidebar');
    const toggleIcon = toggleButton ? toggleButton.querySelector('i') : null;
    const alerts = document.querySelectorAll('.alert-dismissible');

    alerts.forEach(alert => {
        setTimeout(() => {
            const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
            bsAlert.close();
        }, 10000);
    });

    function activateSection(sectionId) {
        navLinks.forEach(link => {
            link.classList.toggle(
                'active',
                link.getAttribute('data-section') === sectionId
            );
        });

        sections.forEach(sec => {
            sec.classList.toggle(
                'active',
                sec.id === sectionId
            );
        });
    }

    let savedSection = localStorage.getItem('activeSidebarSection') || 'select';

    if (![...sections].some(sec => sec.id === savedSection)) {
        savedSection = navLinks.length
            ? navLinks[0].getAttribute('data-section')
            : null;
    }

    if (savedSection) {
        activateSection(savedSection);
    }

    navLinks.forEach(link => {
        link.addEventListener('click', () => {
            const selectedSection = link.getAttribute('data-section');
            localStorage.setItem('activeSidebarSection', selectedSection);
            activateSection(selectedSection);
        });
    });

    // ========================================================
    // SECONDARY START
    // ========================================================

    const secondaryStartMode = document.getElementById('secondaryStartMode');
    const secondaryStartDelayGroup = document.getElementById('secondaryStartDelayGroup');

    function updateSecondaryStartUI() {
        if (!secondaryStartMode || !secondaryStartDelayGroup) {
            return;
        }

        secondaryStartDelayGroup.style.display =
            secondaryStartMode.value === 'after_delay' ? 'block' : 'none';
    }

    if (secondaryStartMode) {
        secondaryStartMode.addEventListener('change', updateSecondaryStartUI);
        updateSecondaryStartUI();
    }

    
    // ========================================================
// APPLICATION UPDATES
// ========================================================

const checkUpdatesBtn =
    document.getElementById('check-updates-btn');

const updateNowBtn =
    document.getElementById('update-now-btn');

const latestVersionElement =
    document.getElementById('latest-version');

const updateStatusElement =
    document.getElementById('update-status');

const stableChannel =
    document.getElementById('stableChannel');

const betaChannel =
    document.getElementById('betaChannel');

const updateProgressContainer =
    document.getElementById('update-progress-container');

const updateProgress =
    document.getElementById('update-progress');

let availableReleaseTag = null;
let updateStatusTimer = null;


function showUpdateProgress(history) {

    if (!updateProgressContainer || !updateProgress) {
        return;
    }

    updateProgressContainer.classList.remove('d-none');

    updateProgress.innerHTML = '';

    if (!history || history.length === 0) {
        return;
    }

    history.forEach(step => {

        const row = document.createElement('div');

        row.className =
            'd-flex align-items-start mb-2';

        let icon = '✓';
        let iconClass = 'text-success';

        if (step.status === 'restarting' ||
            step.status === 'starting' ||
            step.status === 'downloading' ||
            step.status === 'extracting' ||
            step.status === 'backing_up' ||
            step.status === 'installing') {

            icon = '⟳';
            iconClass = 'text-primary';
        }

        if (step.error) {
            icon = '✗';
            iconClass = 'text-danger';
        }

        row.innerHTML = `
            <div
                class="${iconClass} fw-bold me-2"
                style="width: 20px;">
                ${icon}
            </div>

            <div class="flex-grow-1">
                ${step.message}
            </div>

            <div class="text-muted small ms-3">
                ${step.time || ''}
            </div>
        `;

        updateProgress.appendChild(row);
    });

    updateProgress.scrollTop =
        updateProgress.scrollHeight;
}


async function checkUpdateStatus() {

    try {

        const response =
            await fetch('/update_status');

        if (!response.ok) {
            return;
        }

        const data =
            await response.json();

        showUpdateProgress(
            data.history || []
        );

        if (data.status === 'complete') {

            if (updateStatusElement) {

                updateStatusElement.className =
                    'alert alert-success';

                updateStatusElement.textContent =
                    data.message ||
                    'Update completed successfully.';
            }

            
            //if (refreshUiContainer) {
            //    refreshUiContainer.classList.add('d-none');
            //}

            stopUpdateStatusPolling();

            if (updateNowBtn) {
                updateNowBtn.disabled = false;
            }

            if (checkUpdatesBtn) {
                checkUpdatesBtn.disabled = false;
            }

        } else if (data.status === 'failed') {

            if (updateStatusElement) {

                updateStatusElement.className =
                    'alert alert-danger';

                updateStatusElement.textContent =
                    data.message ||
                    'The update failed.';
            }

            stopUpdateStatusPolling();

            if (updateNowBtn) {
                updateNowBtn.disabled = false;
            }

            if (checkUpdatesBtn) {
                checkUpdatesBtn.disabled = false;
            }

        } else if (
            data.status &&
            data.status !== 'idle'
        ) {

            if (updateStatusElement) {

                updateStatusElement.className =
                    'alert alert-info';

                updateStatusElement.textContent =
                    data.message ||
                    'Update in progress...';
            }
        }

    } catch (error) {

        console.error(
            'Unable to read update status:',
            error
        );
    }
}


function startUpdateStatusPolling() {

    stopUpdateStatusPolling();

    checkUpdateStatus();

    updateStatusTimer =
        setInterval(
            checkUpdateStatus,
            1000
        );
}


function stopUpdateStatusPolling() {

    if (updateStatusTimer) {

        clearInterval(
            updateStatusTimer
        );

        updateStatusTimer = null;
    }
}


if (
    checkUpdatesBtn &&
    latestVersionElement &&
    updateStatusElement
) {

    checkUpdatesBtn.addEventListener(
        'click',
        async () => {

            const channel =
                betaChannel &&
                betaChannel.checked
                    ? 'beta'
                    : 'stable';

            checkUpdatesBtn.disabled = true;

            if (updateNowBtn) {

                updateNowBtn.classList.add(
                    'd-none'
                );

                updateNowBtn.disabled = false;
            }

            availableReleaseTag = null;

            latestVersionElement.textContent =
                'Checking...';

            latestVersionElement.className =
                'badge bg-secondary fs-6';

            updateStatusElement.className =
                'alert alert-secondary';

            updateStatusElement.textContent =
                'Checking GitHub for the latest release...';

            try {

                const response =
                    await fetch(
                        `/check_updates?channel=${channel}`
                    );

                const data =
                    await response.json();

                if (
                    !response.ok ||
                    !data.success
                ) {

                    throw new Error(
                        data.error ||
                        'Unable to check for updates.'
                    );
                }

                latestVersionElement.textContent =
                    data.latest_version;

                if (data.update_available) {

                    latestVersionElement.className =
                        'badge bg-warning text-dark fs-6';

                    updateStatusElement.className =
                        'alert alert-success';

                    updateStatusElement.textContent =
                        `Update available: ${data.latest_version}`;

                    availableReleaseTag =
                        data.tag_name;

                    if (updateNowBtn) {

                        updateNowBtn.classList.remove(
                            'd-none'
                        );
                    }

                } else {

                    latestVersionElement.className =
                        'badge bg-success fs-6';

                    updateStatusElement.className =
                        'alert alert-success';

                    updateStatusElement.textContent =
                        'Your application is up to date.';
                }

            } catch (error) {

                latestVersionElement.textContent =
                    'Check failed';

                latestVersionElement.className =
                    'badge bg-danger fs-6';

                updateStatusElement.className =
                    'alert alert-danger';

                updateStatusElement.textContent =
                    `Unable to check for updates: ${error.message}`;

            } finally {

                checkUpdatesBtn.disabled = false;
            }
        }
    );
}


// ========================================================
// UPDATE NOW
// ========================================================

if (updateNowBtn) {

    updateNowBtn.addEventListener(
        'click',
        async () => {

            if (!availableReleaseTag) {
                return;
            }

            const confirmed =
                confirm(
                    `Update LivingPortraitApp to ${availableReleaseTag}?\n\n` +
                    `The application will restart after the update.`
                );

            if (!confirmed) {
                return;
            }

            updateNowBtn.disabled = true;

            if (checkUpdatesBtn) {
                checkUpdatesBtn.disabled = true;
            }

            if (updateProgressContainer) {

                updateProgressContainer.classList.remove(
                    'd-none'
                );
            }

            if (updateProgress) {
                updateProgress.innerHTML = '';
            }

            if (updateStatusElement) {

                updateStatusElement.className =
                    'alert alert-info';

                updateStatusElement.textContent =
                    `Starting update to ${availableReleaseTag}...`;
            }

            try {

                const response =
                    await fetch(
                        '/start_update',
                        {
                            method: 'POST',
                            headers: {
                                'Content-Type':
                                    'application/json',
                                'X-CSRF-Token':
                                    document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || ''
                            },
                            body: JSON.stringify({
                                tag_name:
                                    availableReleaseTag
                            })
                        }
                    );

                const data =
                    await response.json();

                if (
                    !response.ok ||
                    !data.success
                ) {

                    throw new Error(
                        data.error ||
                        'Unable to start update.'
                    );
                }

                if (updateStatusElement) {

                    updateStatusElement.className =
                        'alert alert-info';

                    updateStatusElement.textContent =
                        'Update started. Watching update progress...';
                }

                startUpdateStatusPolling();

            } catch (error) {

                updateNowBtn.disabled = false;

                if (checkUpdatesBtn) {
                    checkUpdatesBtn.disabled = false;
                }

                if (updateStatusElement) {

                    updateStatusElement.className =
                        'alert alert-danger';

                    updateStatusElement.textContent =
                        `Unable to start update: ${error.message}`;
                }
            }
        }
    );
}
    

    // ========================================================
    // SIDEBAR TOGGLE
    // ========================================================

    if (toggleButton && sidebar && content && toggleIcon) {
        toggleButton.addEventListener('click', () => {
            sidebar.classList.toggle('collapsed');
            content.classList.toggle('collapsed');

            if (sidebar.classList.contains('collapsed')) {
                toggleIcon.classList.remove('bi-chevron-left');
                toggleIcon.classList.add('bi-chevron-right');
            } else {
                toggleIcon.classList.remove('bi-chevron-right');
                toggleIcon.classList.add('bi-chevron-left');
            }
        });
    }


    // ========================================================
    // THEME & FONT
    // ========================================================

    function getCookie(name) {
        const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
        return match ? decodeURIComponent(match[2]) : null;
    }

    function setCookie(name, value, days = 30) {
        const expires = new Date(Date.now() + days * 86400 * 1000).toUTCString();
        document.cookie = `${name}=${encodeURIComponent(value)}; expires=${expires}; path=/`;
    }

    function setTheme(mode) {
        document.body.classList.toggle('dark-theme', mode === 'dark');
        localStorage.setItem('themeMode', mode);
        setCookie('themeMode', mode);
        updateIconTheme(mode);
    }

    function updateIconTheme(mode) {
        const icon = document.getElementById('themeIcon');

        if (!icon) return;

        icon.classList.remove('text-light', 'text-dark');
        icon.classList.add(mode === 'dark' ? 'text-light' : 'text-dark');
    }

    function setFont(font) {
        document.body.style.fontFamily = font;
        localStorage.setItem('fontFamily', font);
        setCookie('fontFamily', font);
    }


    // ========================================================
    // THEME COLORS
    // ========================================================

    const defaultPrimaryColor = '#0d6efd';
    const defaultSecondaryColor = '#084298';
    const defaultFontColor = '#6c757d';

    function setThemeColors(primaryColor, secondaryColor, fontColor) {
        document.documentElement.style.setProperty(
            '--primary-color',
            primaryColor
        );

        document.documentElement.style.setProperty(
            '--secondary-color',
            secondaryColor
        );

        document.documentElement.style.setProperty(
            '--font-color',
            fontColor
        );

        localStorage.setItem('primaryColor', primaryColor);
        localStorage.setItem('secondaryColor', secondaryColor);
        localStorage.setItem('fontColor', fontColor);

        setCookie('primaryColor', primaryColor);
        setCookie('secondaryColor', secondaryColor);
        setCookie('fontColor', fontColor);
    }

    const savedTheme = localStorage.getItem('themeMode') || getCookie('themeMode') || 'light';
    const savedFont = localStorage.getItem('fontFamily') || getCookie('fontFamily') || "'Roboto', sans-serif";

    const savedPrimaryColor =
        localStorage.getItem('primaryColor') ||
        getCookie('primaryColor') ||
        defaultPrimaryColor;

    const savedSecondaryColor =
        localStorage.getItem('secondaryColor') ||
        getCookie('secondaryColor') ||
        defaultSecondaryColor;

    const savedFontColor =
        localStorage.getItem('fontColor') ||
        getCookie('fontColor') ||
        defaultFontColor;

    setTheme(savedTheme);
    setFont(savedFont);
    updateIconTheme(savedTheme);

    setThemeColors(
        savedPrimaryColor,
        savedSecondaryColor,
        savedFontColor
    );


    // ========================================================
    // THEME SWITCH
    // ========================================================

    const lightSwitch = document.getElementById('lightSwitch');

    if (lightSwitch) {
        lightSwitch.checked = savedTheme === 'dark';

        lightSwitch.addEventListener('change', () => {
            setTheme(lightSwitch.checked ? 'dark' : 'light');
        });
    }


    // ========================================================
    // FONT SELECTION
    // ========================================================

    const fontRadios = document.querySelectorAll('input[name="font"]');

    fontRadios.forEach(radio => {
        if (radio.value === savedFont) {
            radio.checked = true;
        }

        radio.addEventListener('change', () => {
            if (radio.checked) {
                setFont(radio.value);
            }
        });
    });


    // ========================================================
    // COLOR SELECTION
    // ========================================================

    const primaryColorPicker = document.getElementById('primaryColor');
    const secondaryColorPicker = document.getElementById('secondaryColor');
    const fontColorPicker = document.getElementById('fontColor');
    const resetThemeColors = document.getElementById('resetThemeColors');


    if (primaryColorPicker && secondaryColorPicker && fontColorPicker) {

        primaryColorPicker.value = savedPrimaryColor;
        secondaryColorPicker.value = savedSecondaryColor;
        fontColorPicker.value = savedFontColor;

        primaryColorPicker.addEventListener('input', () => {
            setThemeColors(
                primaryColorPicker.value,
                secondaryColorPicker.value,
                fontColorPicker.value
            );
        });

        secondaryColorPicker.addEventListener('input', () => {
            setThemeColors(
                primaryColorPicker.value,
                secondaryColorPicker.value,
                fontColorPicker.value
            );
        });

        fontColorPicker.addEventListener('input', () => {
            setThemeColors(
                primaryColorPicker.value,
                secondaryColorPicker.value,
                fontColorPicker.value
            );

            console.log(
                "CSS FONT:",
                getComputedStyle(document.documentElement)
                    .getPropertyValue('--font-color')
            );
        });
    }


    // ========================================================
    // RESET THEME COLORS
    // ========================================================

    if (resetThemeColors) {
        resetThemeColors.addEventListener('click', () => {

            primaryColorPicker.value = defaultPrimaryColor;
            secondaryColorPicker.value = defaultSecondaryColor;
            fontColorPicker.value = defaultFontColor;

            setThemeColors(
                defaultPrimaryColor,
                defaultSecondaryColor,
                defaultFontColor
            );
        });
    }


    }
});

// ============================================================
// GLOBAL FUNCTIONS
// ============================================================

async function deleteVideo(filename) {
    if (!confirm(`Delete ${filename}?`)) return;

    const item = Array.from(document.querySelectorAll('.video-library-item'))
        .find(row => row.querySelector('input[name$="[filename]"]')?.value === filename);
    const button = item?.querySelector('button[aria-label^="Delete"]');
    if (button) {
        button.disabled = true;
        button.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span>';
    }

    try {
        const response = await fetch(`/delete/${encodeURIComponent(filename)}`, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Unable to delete video.');
        }

        item?.remove();
        const list = document.getElementById('videoLibraryList');
        if (list && !list.querySelector('.video-library-item')) {
            list.innerHTML = '<li class="list-group-item text-muted">No videos found.</li>';
        }
        if (typeof showToast === 'function') showToast(data.message || 'Video deleted.', 'success');
    } catch (error) {
        if (button) {
            button.disabled = false;
            button.innerHTML = '<i class="bi bi-trash" aria-hidden="true"></i>';
        }
        window.alert(error.message || 'Unable to delete video.');
    }
}

