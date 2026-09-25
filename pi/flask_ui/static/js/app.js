// ============================================================
// CLOCK
// ============================================================

function updateClock() {
    const now = new Date();
    const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
    const dayName = days[now.getDay()];
    const timeString = now.toLocaleTimeString('en-US', {
        hour12: true,
        hour: 'numeric',
        minute: '2-digit',
        second: '2-digit'
    });
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

    // ========================================================
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
        ? new bootstrap.Modal(validationModalElement)
        : null;
    const modalBody = document.getElementById('validationModalBody');

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

    // ========================================================
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
        uploadForm.addEventListener('submit', () => {
            document.getElementById('loadingOverlay').style.display = 'flex';
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
        ['dragenter', 'dragover'].forEach(eventName => {
            dropArea.addEventListener(eventName, e => {
                e.preventDefault();
                e.stopPropagation();
                dropArea.classList.add('border-success', 'bg-light');
            });
        });

        ['dragleave', 'drop'].forEach(eventName => {
            dropArea.addEventListener(eventName, e => {
                e.preventDefault();
                e.stopPropagation();
                dropArea.classList.remove('border-success', 'bg-light');
            });
        });

        dropArea.addEventListener('drop', e => {
            const files = e.dataTransfer.files;
            if (files.length > 0) handleFile(files[0]);
        });

        fileInput.addEventListener('change', e => {
            if (e.target.files.length > 0) handleFile(e.target.files[0]);
        });

        function handleFile(file) {
            if (file.type === "video/mp4") {
                const dt = new DataTransfer();
                dt.items.add(file);
                fileInput.files = dt.files;
                fileName.textContent = `Selected: ${file.name}`;
                uploadBtn.disabled = false;
            } else {
                fileName.textContent = "Please upload a valid MP4 file.";
                uploadBtn.disabled = true;
            }
        }
    }

    // ========================================================
    // PLAYLIST MODE
    // ========================================================

    const modeSelect = document.getElementById('modeSelect');
    const intervalGroup = document.getElementById('intervalGroup');
    const intervalSelect = document.getElementById('interval');
    const singleVideoGroup = document.getElementById('singleVideoSelectGroup');
    const fixedPlaylistGroup = document.getElementById('fixedPlaylistGroup');

    function updateModeUI() {
        if (!modeSelect) return;

        const mode = modeSelect.value;

        if (mode === 'random' || mode === 'fixed') {
            intervalGroup.style.display = 'block';
            intervalSelect.disabled = false;
        } else {
            intervalGroup.style.display = 'none';
            intervalSelect.disabled = true;
        }

        singleVideoGroup.style.display = (mode === 'single') ? 'block' : 'none';
        fixedPlaylistGroup.style.display = (mode === 'fixed') ? 'block' : 'none';
    }

    if (modeSelect) {
        modeSelect.addEventListener('change', updateModeUI);
        updateModeUI();
    }

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
                    .map(li => li.textContent.trim());
                fixedOrderInput.value = order.join(',');
            }
        });

        const initialOrder = Array.from(fixedPlaylist.querySelectorAll('li'))
            .map(li => li.textContent.trim());

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
                                    'application/json'
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


});

// ============================================================
// GLOBAL FUNCTIONS
// ============================================================

function deleteVideo(filename) {
    if (confirm(`Delete ${filename}?`)) {
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = `/delete/${filename}`;
        document.body.appendChild(form);
        form.submit();
    }
}

