document.addEventListener('DOMContentLoaded', () => {
    const steps = document.querySelectorAll('.step-card');
    const btnStart = document.getElementById('btn-start');
    const btnNext = document.querySelector('.btn-next');
    const checkbox = document.getElementById('consent-checkbox');
    const btnConsent = document.getElementById('btn-consent');
    const progressBarContainer = document.getElementById('progress-container');
    const progressBar = document.getElementById('progress-bar');
    const modal = document.getElementById('thank-you-modal');
    const apiBaseUrl = `${window.location.protocol}//${window.location.host}`;

    let currentStep = 0;
    let consentTimeout = null;

    // Time (ms) to show each text card automatically
    const AUTO_PLAY_DELAY = 1500; 

    function updateProgress() {
        // Steps 2,3,4,5 are the actual content steps (total 4)
        if(currentStep >= 2) {
            progressBarContainer.classList.remove('hidden');
            const progress = ((currentStep - 1) / (steps.length - 2)) * 100;
            progressBar.style.width = `${progress}%`;
        }
    }

    function goToNextStep() {
        if (currentStep >= steps.length - 1) return;

        const currentCard = steps[currentStep];
        const nextCard = steps[currentStep + 1];

        // Animate out
        currentCard.classList.remove('active');
        currentCard.classList.add('exit');

        // Animate in next card
        currentStep++;
        nextCard.classList.remove('exit');
        nextCard.classList.add('active');
        
        // If the next card is the motion graphic, inject the iframe NOW so it starts fresh
        if (nextCard.id === 'step-1') {
            const container = document.getElementById('motion-container');
            if (container && !container.innerHTML.includes('iframe')) {
                container.innerHTML = '<iframe class="motion-frame" src="motion-graphic.html" title="โมชั่นกราฟิก"></iframe>';
            }
        }

        updateProgress();

        // If it's an info card (steps 2,3,4), auto-play to the next one
        if (currentStep >= 2 && currentStep < steps.length - 1) {
            setTimeout(goToNextStep, AUTO_PLAY_DELAY);
        }
    }

    btnStart.addEventListener('click', goToNextStep);
    
    // User clicks next on the motion graphic manually (or we could auto-skip)
    if(btnNext) {
        btnNext.addEventListener('click', goToNextStep);
    }

    // Toggle button state based on checkbox
    checkbox.addEventListener('change', (e) => {
        btnConsent.disabled = !e.target.checked;
    });

    // Helper: update backend state
    async function updateBackendState(status, consent = null) {
        try {
            const payload = { status };
            if (consent) {
                payload.consent = consent;
            }
            await fetch(`${apiBaseUrl}/api/state`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            return true;
        } catch (err) {
            console.error("Error updating backend state", err);
            return false;
        }
    }

    function getConsentId() {
        let consentId = sessionStorage.getItem('pharmatalk_consent_id');
        if (!consentId) {
            consentId = crypto.randomUUID();
            sessionStorage.setItem('pharmatalk_consent_id', consentId);
        }
        return consentId;
    }

    // Submit Consent
    btnConsent.addEventListener('click', async () => {
        modal.classList.add('active');
        
        await updateBackendState("READY", {
            consent_id: getConsentId(),
            consent_version: '2.0',
            consented_at: new Date().toISOString()
        });

        // Set 30-second timeout to cancel consent if recording doesn't start
        consentTimeout = setTimeout(() => {
            updateBackendState("WAITING");
            window.location.reload();
        }, 30000);

        // Polling loop to wait for RECORDING or FINISHED
        const pollInterval = setInterval(async () => {
            try {
                const res = await fetch(`${apiBaseUrl}/api/state`);
                const data = await res.json();
                
                if (data.status === 'RECORDING') {
                    // Recording started, clear the timeout
                    if (consentTimeout) {
                        clearTimeout(consentTimeout);
                        consentTimeout = null;
                    }
                } else if (data.status === 'FINISHED') {
                    if (consentTimeout) {
                        clearTimeout(consentTimeout);
                        consentTimeout = null;
                    }
                    clearInterval(pollInterval);
                    // Reset to home page, but DO NOT change backend state (pharmacist must manually start new patient)
                    setTimeout(() => {
                        window.location.reload(); 
                    }, 3000);
                }
            } catch (err) {}
        }, 1000);
    });
});
