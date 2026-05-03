export function isVideoFromYoutube(videoURL) {
    if (!videoURL || typeof videoURL !== 'string') return false;
    let url = videoURL.trim();
    if (!/^[a-zA-Z][a-zA-Z\d+\-.]*:\/\//.test(url)) {
        url = 'https://' + url;
    }

    try {
        const u = new URL(url);
        const host = u.hostname.toLowerCase();

        const isYoutuBe = host === 'youtu.be' || host.endsWith('.youtu.be');
        const isYoutubeDomain =
            host === 'youtube.com' ||
            host.endsWith('.youtube.com') ||
            host === 'youtube-nocookie.com' ||
            host.endsWith('.youtube-nocookie.com');

        if (isYoutuBe) return !!u.pathname.replace(/\//g, '');
        if (!isYoutubeDomain) return false;

        const path = u.pathname;
        if (u.searchParams.has('v')) return true;
        return /^\/(embed|v|shorts)\/[^/]+/.test(path);
    } catch (e) {
        return false;
    }
}

export function setIPv6First(sdp) {
    let lines = sdp.split('\r\n');
    let candidates = [];
    let out = [];
    for (let line of lines) {
        if (line.startsWith('a=candidate:')) {
            candidates.push(line);
        } else {
            if (candidates.length > 0) {
                candidates.sort((a, b) => {
                    let ipA = a.split(' ')[4];
                    let ipB = b.split(' ')[4];
                    let aIsV6 = ipA && ipA.includes(':');
                    let bIsV6 = ipB && ipB.includes(':');
                    return (aIsV6 === bIsV6) ? 0 : (aIsV6 ? -1 : 1);
                });
                out.push(...candidates);
                candidates = [];
            }
            out.push(line);
        }
    }
    if (candidates.length > 0) {
        candidates.sort((a, b) => {
            let ipA = a.split(' ')[4];
            let ipB = b.split(' ')[4];
            let aIsV6 = ipA && ipA.includes(':');
            let bIsV6 = ipB && ipB.includes(':');
            return (aIsV6 === bIsV6) ? 0 : (aIsV6 ? -1 : 1);
        });
        out.push(...candidates);
    }
    return out.join('\r\n');
}
