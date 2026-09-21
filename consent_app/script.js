// script.js for PharmaTalk Consent Form

document.addEventListener('DOMContentLoaded', () => {
    const checkbox = document.getElementById('consent-checkbox');
    const btnConsent = document.getElementById('btn-consent');
    const modal = document.getElementById('thank-you-modal');
    const btnCloseModal = document.getElementById('btn-close-modal');
    
    // Select modal content elements to update dynamically
    const modalIcon = document.querySelector('.modal-icon-success');
    const modalTitle = document.querySelector('.modal-content h2');
    const modalDesc = document.querySelector('.modal-content p');

    let pollInterval = null;

    // Toggle button state based on checkbox
    checkbox.addEventListener('change', (e) => {
        if (e.target.checked) {
            btnConsent.disabled = false;
        } else {
            btnConsent.disabled = true;
        }
    });

    // Helper: update backend state
    async function updateBackendState(status) {
        try {
            await fetch('/api/state', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ status: status })
            });
        } catch (err) {
            console.error("Error updating backend state", err);
        }
    }

    // Helper: reset UI to initial state
    function resetUI() {
        modal.classList.remove('active');
        setTimeout(() => {
            checkbox.checked = false;
            btnConsent.disabled = true;
        }, 300);
    }

    // Polling function to check for 'FINISHED'
    async function pollState() {
        try {
            const res = await fetch('/api/state');
            const data = await res.json();
            
            if (data.status === 'FINISHED') {
                clearInterval(pollInterval);
                
                // Update modal to finish state
                modalIcon.innerHTML = `
                    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M20 6L9 17L4 12" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                `;
                modalTitle.innerText = "ระบบบันทึกเสียงเสร็จสิ้น";
                modalTitle.style.color = '#047857'; // Green
                modalDesc.innerText = "รอสักครู่ ระบบกำลังกลับสู่หน้าหลัก...";
                btnCloseModal.style.display = 'none';

                // Automatically reset after 3 seconds
                setTimeout(() => {
                    updateBackendState("WAITING");
                    resetUI();
                }, 3000);
            }
        } catch (err) {
            console.error("Polling error", err);
        }
    }

    // Show modal when consent button is clicked
    btnConsent.addEventListener('click', async () => {
        // Change UI to Ready state
        modalIcon.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M20 6L9 17L4 12" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
        `;
        
        modalTitle.innerText = "ขอบคุณที่ให้ความยินยอม";
        modalTitle.style.color = '#047857';
        modalDesc.innerHTML = "กำลังรอเภสัชกรเริ่มการบันทึกเสียง...<br><strong>สามารถสนทนากับเภสัชกรได้ตามปกติ</strong>";
        
        // Hide close button during this phase
        btnCloseModal.style.display = 'none';

        modal.classList.add('active');

        // Tell backend we are READY
        await updateBackendState("READY");

        // Start polling for FINISHED state
        pollInterval = setInterval(pollState, 1000);
    });

    // Close modal when 'ตกลง' is clicked (if it's ever shown manually)
    btnCloseModal.addEventListener('click', () => {
        clearInterval(pollInterval);
        updateBackendState("WAITING");
        resetUI();
    });
});
