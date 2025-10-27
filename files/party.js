const sidebar = document.getElementById('sidebar');
const toggleBtn = document.getElementById('sidebar-toggle');

function toggleSidebar() {
    sidebar.classList.toggle('collapsed');
    if (sidebar.classList.contains('collapsed')) {
        toggleBtn.innerHTML = '<';
        toggleBtn.title = 'Expandir chat';
    } else {
        toggleBtn.innerHTML = '>';
        toggleBtn.title = 'Recolher chat';
    }
}

toggleBtn.addEventListener('click', toggleSidebar);
toggleBtn.addEventListener('click', toggleSidebar);
document.addEventListener('keydown', (e) => {
    if (e.key === 'Tab') {
        e.preventDefault();
        toggleSidebar();
    }
});
