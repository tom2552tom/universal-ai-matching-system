(function() {
    const streamlitDoc = window.parent.document;

    function applyTheme() {
        // iframeが読み込まれるのを待つ
        const iframe = streamlitDoc.querySelector('iframe');
        if (!iframe) {
            setTimeout(applyTheme, 50); // 50ms後に再試行
            return;
        }

        const body = iframe.contentDocument.querySelector('body');
        if (!body) {
            setTimeout(applyTheme, 50); // 50ms後に再試行
            return;
        }

        const theme = body.dataset.theme;
        const rootBody = streamlitDoc.body;
        
        if (theme === 'dark') {
            rootBody.style.setProperty('--text-container-bg', '#1a1a1a');
            rootBody.style.setProperty('--text-container-border', '#333');
        } else {
            rootBody.style.setProperty('--text-container-bg', '#f0f2f6');
            rootBody.style.setProperty('--text-container-border', '#ccc');
        }
    }

    function observeThemeChanges() {
        const iframe = streamlitDoc.querySelector('iframe');
        if (!iframe) {
            setTimeout(observeThemeChanges, 50);
            return;
        }
        
        const targetNode = iframe.contentDocument.querySelector('body');
        if (!targetNode) {
            setTimeout(observeThemeChanges, 50);
            return;
        }

        const observer = new MutationObserver((mutationsList) => {
            for(const mutation of mutationsList) {
                if (mutation.type === 'attributes' && mutation.attributeName === 'data-theme') {
                    applyTheme();
                }
            }
        });
        observer.observe(targetNode, { attributes: true });
    }

    // DOMの準備ができたら実行
    if (streamlitDoc.readyState === 'complete' || streamlitDoc.readyState === 'interactive') {
        applyTheme();
        observeThemeChanges();
    } else {
        streamlitDoc.addEventListener('DOMContentLoaded', () => {
            applyTheme();
            observeThemeChanges();
        });
    }
})();
