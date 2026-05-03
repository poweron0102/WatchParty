const notificationContainer = (() => {
    const container = document.createElement('div');
    container.id = 'notification-container';
    document.body.appendChild(container);
    return container;
})();

export function showNotification(message, type = 'info', actions = []) {
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;

    const icons = {
        info: `<svg class="notification-icon" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd"></path></svg>`,
        success: `<svg class="notification-icon" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"></path></svg>`,
        warning: `<svg class="notification-icon" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM10 5a1 1 0 011 1v3a1 1 0 11-2 0V6a1 1 0 011-1zm1 5a1 1 0 10-2 0v2a1 1 0 102 0v-2z" clip-rule="evenodd"></path></svg>`
    };

    notification.innerHTML = `
        ${icons[type] || icons.info}
        <div class="notification-content">${message}</div>
    `;

    if (actions.length > 0) {
        const actionsContainer = document.createElement('div');
        actionsContainer.className = 'notification-actions';
        actions.forEach(action => {
            const button = document.createElement('button');
            button.className = `notification-action-btn ${action.className || ''}`;
            button.textContent = action.text;
            button.onclick = (e) => {
                e.stopPropagation();
                action.callback();
                notification.remove();
            };
            actionsContainer.appendChild(button);
        });
        notification.appendChild(actionsContainer);
    }

    notificationContainer.appendChild(notification);

    if (actions.length === 0) {
        setTimeout(() => { notification.remove(); }, 5000);
    } else {
        const closeBtn = document.createElement('button');
        closeBtn.className = 'notification-close-btn';
        closeBtn.innerHTML = '&times;';
        closeBtn.onclick = () => notification.remove();
        notification.appendChild(closeBtn);
    }
}
