(() => {
    const firstStepDelay = 2200;
    const stepInterval = 4200;
    const completionDelay = 3200;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    function startAutoScroll() {
        const cards = Array.from(document.querySelectorAll('[data-idx]'))
            .sort((left, right) => Number(left.dataset.idx) - Number(right.dataset.idx));

        if (cards.length !== 6) {
            return;
        }

        const behavior = reducedMotion ? 'auto' : 'smooth';
        let currentCard = 0;

        function revealNext() {
            if (currentCard < cards.length) {
                cards[currentCard].scrollIntoView({ behavior, block: 'center' });
                currentCard += 1;
                window.setTimeout(revealNext, stepInterval);
                return;
            }

            const summary = document.querySelector('#root footer, #root [role="contentinfo"]');
            if (summary) {
                summary.scrollIntoView({ behavior, block: 'center' });
            }

            window.setTimeout(() => {
                try {
                    const parentWindow = window.parent;
                    const parentDocument = parentWindow.document;
                    const consentForm = parentDocument.getElementById('consent-form');
                    const motionContinue = parentDocument.querySelector('.motion-continue');
                    const scrollContainer = parentDocument.querySelector('.document-content');

                    if (consentForm) {
                        if (motionContinue) {
                            motionContinue.classList.add('is-ready');
                        }

                        if (scrollContainer) {
                            scrollContainer.scrollTo({
                                top: consentForm.offsetTop - 18,
                                behavior
                            });
                        } else {
                            consentForm.scrollIntoView({ behavior, block: 'start' });
                        }

                        if (parentWindow.location.hash !== '#consent-form') {
                            parentWindow.location.hash = '#consent-form';
                        }
                    }
                } catch (error) {
                    console.warn('Auto-scroll fallback to parent failed:', error);
                }

                window.parent.postMessage(
                    { type: 'pharmatalk-motion-complete' },
                    '*'
                );
            }, completionDelay);
        }

        window.setTimeout(revealNext, firstStepDelay);
    }

    function waitForCards(attempt = 0) {
        if (document.querySelectorAll('[data-idx]').length === 6) {
            startAutoScroll();
            return;
        }

        if (attempt < 100) {
            window.setTimeout(() => waitForCards(attempt + 1), 100);
        }
    }

    waitForCards();
})();