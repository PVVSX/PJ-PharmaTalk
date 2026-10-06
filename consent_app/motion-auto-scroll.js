(() => {
    const firstStepDelay = 1000;
    const stepInterval = 1500;
    const completionDelay = 2000;
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