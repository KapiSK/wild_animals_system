document.addEventListener('DOMContentLoaded', () => {
    let currentImages = [];
    const latestContainer = document.getElementById('latest-container');
    const galleryGrid = document.getElementById('gallery-grid');
    const modal = document.getElementById('image-modal');
    const modalImg = document.getElementById('modal-img');
    const captionText = document.getElementById('caption');
    const closeBtn = document.getElementsByClassName('close-btn')[0];

    // Array equality check
    function arraysEqual(a, b) {
        if (a === b) return true;
        if (a == null || b == null) return false;
        if (a.length !== b.length) return false;
        for (let i = 0; i < a.length; ++i) {
            if (a[i] !== b[i]) return false;
        }
        return true;
    }

    // Parse filename to extract info if possible (depends on format)
    function parseFilename(filename) {
        // format usually: timestamp_pi_RcvHHMMSS_original.jpg
        return filename;
    }

    function formatTime() {
        const now = new Date();
        return now.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }

    function updateUI(images) {
        if (!images || images.length === 0) {
            latestContainer.innerHTML = `
                <div class="empty-state">
                    <p>No images detected yet.</p>
                </div>
            `;
            latestContainer.className = 'glass-card latest-card';
            galleryGrid.innerHTML = '';
            return;
        }

        const latestImg = images[0];
        const prevLatest = currentImages[0];

        // Update Latest Image
        if (latestImg !== prevLatest || currentImages.length === 0) {
            latestContainer.innerHTML = `
                <img src="/images/${latestImg}" alt="Latest Detection" onclick="openModal(this)">
                <div class="info-bar">
                    <span class="filename">${parseFilename(latestImg)}</span>
                    <span class="time-badge">${formatTime()}</span>
                </div>
            `;
            latestContainer.className = 'glass-card latest-card';
        }

        // Update Gallery
        if (images.length > 1) {
            let html = '';
            for (let i = 1; i < images.length; i++) {
                html += `
                    <div class="glass-card gallery-item" onclick="openModal(this.querySelector('img'))">
                        <div class="img-wrapper">
                            <img src="/images/${images[i]}" alt="Captured Image">
                        </div>
                        <div class="item-info">
                            <p>${parseFilename(images[i])}</p>
                        </div>
                    </div>
                `;
            }
            galleryGrid.innerHTML = html;
        } else {
            galleryGrid.innerHTML = `
                <div class="empty-state" style="grid-column: 1 / -1;">
                    <p>Older captures will appear here.</p>
                </div>
            `;
        }
        
        currentImages = [...images];
    }

    function fetchImages() {
        fetch('/api/images')
            .then(response => response.json())
            .then(data => {
                if (data.status === 'ok') {
                    if (!arraysEqual(currentImages, data.images)) {
                        updateUI(data.images);
                    }
                } else {
                    console.error('API Error:', data.message);
                }
            })
            .catch(err => {
                console.error('Fetch error:', err);
                if(currentImages.length === 0) {
                    latestContainer.innerHTML = `
                        <div class="empty-state" style="color: #ef4444;">
                            <p>Connection Error</p>
                            <small>${err.message}</small>
                        </div>
                    `;
                    latestContainer.className = 'glass-card latest-card';
                }
            });
    }

    // Modal logic
    window.openModal = function(imgElement) {
        modal.style.display = "block";
        // slight delay to allow display:block to apply before adding class for transition
        setTimeout(() => modal.classList.add('show'), 10);
        modalImg.src = imgElement.src;
        captionText.innerHTML = imgElement.nextElementSibling ? imgElement.nextElementSibling.innerText : "Detection Result";
    }

    closeBtn.onclick = function() {
        modal.classList.remove('show');
        setTimeout(() => modal.style.display = "none", 300);
    }

    window.onclick = function(event) {
        if (event.target == modal) {
            modal.classList.remove('show');
            setTimeout(() => modal.style.display = "none", 300);
        }
    }

    // Initial load
    fetchImages();

    // Poll every 5 seconds
    setInterval(fetchImages, 5000);
});
