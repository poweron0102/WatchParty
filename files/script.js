const form = document.getElementById('login-form');
const nameInput = document.getElementById('name');
const fileInput = document.getElementById('pfp');
const cropPanel = document.getElementById('crop-panel');
const cropFrame = document.getElementById('crop-frame');
const preview = document.getElementById('pfp-preview');
const zoomInput = document.getElementById('zoom');
const removePhotoBtn = document.getElementById('remove-photo');
const canvas = document.getElementById('avatar-canvas');

const cropState = {
    file: null,
    objectUrl: '',
    baseWidth: 0,
    baseHeight: 0,
    x: 0,
    y: 0,
    zoom: 1,
    dragging: false,
    dragStartX: 0,
    dragStartY: 0,
    startX: 0,
    startY: 0
};

function getFrameSize() {
    return cropFrame.getBoundingClientRect().width;
}

function constrainPosition() {
    const size = getFrameSize();
    const width = cropState.baseWidth * cropState.zoom;
    const height = cropState.baseHeight * cropState.zoom;
    const minX = size - width;
    const minY = size - height;

    cropState.x = Math.min(0, Math.max(minX, cropState.x));
    cropState.y = Math.min(0, Math.max(minY, cropState.y));
}

function renderPreview() {
    constrainPosition();
    preview.style.width = `${cropState.baseWidth}px`;
    preview.style.height = `${cropState.baseHeight}px`;
    preview.style.transform = `translate(${cropState.x}px, ${cropState.y}px) scale(${cropState.zoom})`;
}

function setBaseImageSize() {
    const size = getFrameSize();
    const coverScale = Math.max(size / preview.naturalWidth, size / preview.naturalHeight);

    cropState.baseWidth = preview.naturalWidth * coverScale;
    cropState.baseHeight = preview.naturalHeight * coverScale;
    cropState.x = (size - cropState.baseWidth * cropState.zoom) / 2;
    cropState.y = (size - cropState.baseHeight * cropState.zoom) / 2;
    renderPreview();
}

function resetPhoto() {
    if (cropState.objectUrl) {
        URL.revokeObjectURL(cropState.objectUrl);
    }

    cropState.file = null;
    cropState.objectUrl = '';
    cropState.zoom = 1;
    fileInput.value = '';
    preview.removeAttribute('src');
    zoomInput.value = '1';
    cropPanel.hidden = true;
    removePhotoBtn.hidden = true;
}

function makeCroppedAvatarBlob() {
    return new Promise((resolve) => {
        const size = getFrameSize();
        const ctx = canvas.getContext('2d');
        const renderedWidth = cropState.baseWidth * cropState.zoom;
        const renderedHeight = cropState.baseHeight * cropState.zoom;
        const sourceX = (-cropState.x / renderedWidth) * preview.naturalWidth;
        const sourceY = (-cropState.y / renderedHeight) * preview.naturalHeight;
        const sourceSizeX = (size / renderedWidth) * preview.naturalWidth;
        const sourceSizeY = (size / renderedHeight) * preview.naturalHeight;

        canvas.width = 512;
        canvas.height = 512;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(preview, sourceX, sourceY, sourceSizeX, sourceSizeY, 0, 0, 512, 512);
        canvas.toBlob(resolve, 'image/png', 0.92);
    });
}

fileInput.addEventListener('change', () => {
    const file = fileInput.files[0];
    if (!file || !file.type.startsWith('image/')) {
        resetPhoto();
        return;
    }

    if (cropState.objectUrl) {
        URL.revokeObjectURL(cropState.objectUrl);
    }

    cropState.file = file;
    cropState.objectUrl = URL.createObjectURL(file);
    cropState.zoom = 1;
    zoomInput.value = '1';
    preview.src = cropState.objectUrl;
    cropPanel.hidden = false;
    removePhotoBtn.hidden = false;
});

preview.addEventListener('load', setBaseImageSize);

zoomInput.addEventListener('input', () => {
    const oldZoom = cropState.zoom;
    const nextZoom = Number(zoomInput.value);
    const size = getFrameSize();
    const centerX = size / 2;
    const centerY = size / 2;

    cropState.x = centerX - ((centerX - cropState.x) / oldZoom) * nextZoom;
    cropState.y = centerY - ((centerY - cropState.y) / oldZoom) * nextZoom;
    cropState.zoom = nextZoom;
    renderPreview();
});

cropFrame.addEventListener('pointerdown', (event) => {
    if (!cropState.file) return;

    cropState.dragging = true;
    cropState.dragStartX = event.clientX;
    cropState.dragStartY = event.clientY;
    cropState.startX = cropState.x;
    cropState.startY = cropState.y;
    cropFrame.setPointerCapture(event.pointerId);
});

cropFrame.addEventListener('pointermove', (event) => {
    if (!cropState.dragging) return;

    cropState.x = cropState.startX + event.clientX - cropState.dragStartX;
    cropState.y = cropState.startY + event.clientY - cropState.dragStartY;
    renderPreview();
});

cropFrame.addEventListener('pointerup', (event) => {
    cropState.dragging = false;
    cropFrame.releasePointerCapture(event.pointerId);
});

cropFrame.addEventListener('pointercancel', () => {
    cropState.dragging = false;
});

removePhotoBtn.addEventListener('click', resetPhoto);

window.addEventListener('resize', () => {
    if (cropState.file && preview.complete) {
        setBaseImageSize();
    }
});

form.onsubmit = async (event) => {
    event.preventDefault();

    const name = nameInput.value.trim();
    let pfpUrl = '';

    if (!name) {
        nameInput.focus();
        return;
    }

    if (cropState.file) {
        const croppedBlob = await makeCroppedAvatarBlob();
        if (!croppedBlob) {
            console.error('Falha ao cortar a foto');
            return;
        }

        const formData = new FormData();
        formData.append('file', croppedBlob, 'avatar.png');

        try {
            const res = await fetch('/api/upload_image', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();
            pfpUrl = data.url || '';
        } catch (err) {
            console.error('Falha no upload da foto', err);
        }
    }

    sessionStorage.setItem('userName', name);
    sessionStorage.setItem('userPfp', pfpUrl);

    window.location.href = '/party';
};
