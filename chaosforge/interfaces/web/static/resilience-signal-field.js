(() => {
    const canvas = document.getElementById("resilience-signal-field");
    if (!canvas || !canvas.getContext) return;

    const context = canvas.getContext("2d", { alpha: true });
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const pathname = window.location.pathname;
    const baseIntensity = pathname === "/" ? 1 : pathname.startsWith("/cloud/") ? 0.82 :
        pathname.startsWith("/service/") ? 0.64 : pathname === "/execution" ? 0.2 : 0.38;
    const intensity = baseIntensity * (window.innerWidth < 720 ? 0.62 : 1);
    const iconBase = "/static/icons/";
    const iconSources = {
        loadBalancer: "Arch_Amazon-Elastic-Load-Balancing_32.svg",
        compute: "EC2-instance-contents_32.svg",
        database: "Arch_Amazon-RDS_32.svg",
        cache: "Arch_Amazon-ElastiCache_32.svg",
        queue: "Arch_Amazon-Simple-Notification-Service_32.svg",
        lambda: "Arch_AWS-Lambda_32.svg",
        gateway: "Arch_Amazon-API-Gateway_32.svg",
        kubernetes: "Arch_Amazon-Elastic-Kubernetes-Service_32.svg",
        storage: "Arch_Amazon-Simple-Storage-Service_32.svg",
    };
    const iconImages = {};
    let width = 0;
    let height = 0;
    let pixelRatio = 1;
    let topology = null;
    let packets = [];
    let disruption = null;
    let animationFrame = null;
    let lastFrame = 0;
    let nextDisruptionAt = 0;

    function preloadIcons() {
        for (const [name, source] of Object.entries(iconSources)) {
            const image = new Image();
            image.src = iconBase + source;
            iconImages[name] = image;
        }
    }

    function curvePoint(link, progress, useFailover = false) {
        const from = topology.nodes[link.from];
        const to = topology.nodes[link.to];
        const controls = useFailover && link.failover ? link.failover : link;
        const inverse = 1 - progress;
        return {
            x: inverse ** 3 * from.x + 3 * inverse ** 2 * progress * controls.control1.x +
                3 * inverse * progress ** 2 * controls.control2.x + progress ** 3 * to.x,
            y: inverse ** 3 * from.y + 3 * inverse ** 2 * progress * controls.control1.y +
                3 * inverse * progress ** 2 * controls.control2.y + progress ** 3 * to.y,
        };
    }

    function normalizedPoint(x, y, role) {
        return {
            x: x * width,
            y: y * height,
            role,
            health: "healthy",
            recoveryUntil: 0,
            phase: Math.random() * Math.PI * 2,
        };
    }

    function controls(from, to, bend) {
        const dx = to.x - from.x;
        const dy = to.y - from.y;
        const length = Math.max(Math.hypot(dx, dy), 1);
        const normalX = -dy / length;
        const normalY = dx / length;
        return {
            control1: { x: from.x + dx * 0.3 + normalX * bend, y: from.y + dy * 0.3 + normalY * bend },
            control2: { x: from.x + dx * 0.7 + normalX * bend, y: from.y + dy * 0.7 + normalY * bend },
        };
    }

    function link(from, to, bend, failoverBend = null) {
        const primary = controls(topology.nodes[from], topology.nodes[to], bend);
        return {
            from,
            to,
            ...primary,
            failover: failoverBend === null ? null : controls(
                topology.nodes[from], topology.nodes[to], failoverBend
            ),
            state: "healthy",
            stateUntil: 0,
            signal: "healthy",
        };
    }

    const architectureBlueprints = [
        {
            name: "web-service",
            roles: ["loadBalancer", "compute", "compute", "cache", "database", "queue"],
            points: [[-0.48, 0], [-0.12, -0.33], [-0.12, 0.33], [0.22, -0.28], [0.52, 0.06], [0.22, 0.36]],
            edges: [[0, 1, -22, 44], [0, 2, 22, -44], [1, 3, 16], [2, 3, -16], [1, 4, -24, 42], [2, 5, 18], [5, 4, -18]],
        },
        {
            name: "event-driven",
            roles: ["gateway", "lambda", "queue", "compute", "database", "storage"],
            points: [[-0.48, 0], [-0.18, 0], [0.12, -0.3], [0.12, 0.3], [0.48, -0.04], [0.48, 0.36]],
            edges: [[0, 1, 0], [1, 2, -24, 42], [1, 3, 24, -42], [2, 4, 20], [3, 4, -22, 40], [3, 5, 18]],
        },
        {
            name: "microservice",
            roles: ["loadBalancer", "kubernetes", "kubernetes", "kubernetes", "cache", "database"],
            points: [[-0.48, 0], [-0.14, -0.35], [-0.14, 0], [-0.14, 0.35], [0.24, -0.22], [0.52, 0.12]],
            edges: [[0, 1, -24, 44], [0, 2, 0], [0, 3, 24, -44], [1, 4, 16], [2, 4, -16], [2, 5, 24, -42], [3, 5, -20, 40], [4, 5, 16]],
        },
        {
            name: "data-path",
            roles: ["compute", "cache", "database", "storage", "queue", "lambda"],
            points: [[-0.46, -0.16], [-0.14, -0.28], [0.22, -0.12], [0.52, 0.16], [-0.14, 0.34], [0.22, 0.34]],
            edges: [[0, 1, -14], [1, 2, 16, -38], [0, 4, 22], [4, 5, -18], [5, 2, 20, -42], [2, 3, 18]],
        },
    ];

    function addArchitectureCluster(blueprint, centerX, centerY, scale) {
        const offset = topology.nodes.length;
        for (let index = 0; index < blueprint.roles.length; index += 1) {
            const [x, y] = blueprint.points[index];
            topology.nodes.push({
                x: centerX + x * scale + (Math.random() - 0.5) * scale * 0.09,
                y: centerY + y * scale + (Math.random() - 0.5) * scale * 0.07,
                role: blueprint.roles[index],
                health: "healthy",
                recoveryUntil: 0,
                phase: Math.random() * Math.PI * 2,
                cluster: topology.clusters.length,
            });
        }
        for (const [from, to, bend, failoverBend] of blueprint.edges) {
            topology.links.push(link(offset + from, offset + to, bend, failoverBend));
        }
        topology.clusters.push({ name: blueprint.name, centerX, centerY, scale });
    }

    function buildTopology() {
        topology = { nodes: [], links: [], clusters: [] };
        const isMobile = width < 720;
        const centers = isMobile ? [
            [width * 0.18, height * 0.22],
            [width * 0.82, height * 0.76],
        ] : [
            [width * 0.14, height * 0.19],
            [width * 0.84, height * 0.2],
            [width * 0.13, height * 0.79],
            [width * 0.86, height * 0.78],
            [width * 0.5, height * 0.88],
        ];
        const clusterCount = isMobile ? 2 : pathname === "/" ? 5 : 4;
        const largeTopologyPage = pathname === "/" || pathname.startsWith("/cloud/");
        const scale = Math.min(width, height) * (
            isMobile ? 0.31 : largeTopologyPage ? 0.38 : 0.3
        );
        for (let index = 0; index < clusterCount; index += 1) {
            const blueprint = architectureBlueprints[index % architectureBlueprints.length];
            addArchitectureCluster(blueprint, centers[index][0], centers[index][1], scale);
        }

        const troubledLinks = topology.links.filter((_, index) => index % 7 === 2 || index % 11 === 5);
        for (const currentLink of troubledLinks) {
            currentLink.signal = currentLink.from % 2 === 0 ? "degraded" : "failed";
        }

        packets = topology.links.flatMap((currentLink, index) => {
            const count = currentLink.signal === "failed" ? 3 :
                currentLink.signal === "degraded" ? 2 : (Math.random() < 0.74 ? 1 : 0);
            return Array.from({ length: count }, (_, packetIndex) => ({
                link: currentLink,
                progress: (Math.random() + packetIndex / Math.max(count, 1)) % 1,
                speed: 0.0026 + Math.random() * 0.0032,
                direction: (index + packetIndex) % 3 === 0 ? -1 : 1,
            }));
        });
        disruption = null;
    }

    function resize() {
        width = window.innerWidth;
        height = window.innerHeight;
        pixelRatio = Math.min(window.devicePixelRatio || 1, 1.5);
        canvas.width = Math.round(width * pixelRatio);
        canvas.height = Math.round(height * pixelRatio);
        canvas.style.width = `${width}px`;
        canvas.style.height = `${height}px`;
        context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
        buildTopology();
        draw(performance.now(), true);
    }

    function drawLink(currentLink, color, widthValue, dashed = false, failover = false) {
        const from = topology.nodes[currentLink.from];
        const to = topology.nodes[currentLink.to];
        const controls = failover ? currentLink.failover : currentLink;
        if (!controls) return;
        context.save();
        if (dashed) context.setLineDash([4, 7]);
        context.beginPath();
        context.strokeStyle = color;
        context.lineWidth = widthValue;
        context.lineCap = "round";
        context.moveTo(from.x, from.y);
        context.bezierCurveTo(
            controls.control1.x, controls.control1.y,
            controls.control2.x, controls.control2.y,
            to.x, to.y
        );
        context.stroke();
        context.restore();
    }

    function startFault(now) {
        const eligible = topology.links.filter((item) => item.failover);
        const targetLink = eligible[Math.floor(Math.random() * eligible.length)];
        if (!targetLink) return;
        const targetNode = topology.nodes[Math.random() < 0.5 ? targetLink.from : targetLink.to];
        targetLink.state = "fault";
        targetLink.stateUntil = now + 1700;
        targetNode.health = "fault";
        targetNode.recoveryUntil = now + 3300;
        disruption = {
            link: targetLink,
            node: targetNode,
            born: now,
            duration: 2600,
            maxRadius: 46 + Math.random() * 36,
        };
        nextDisruptionAt = now + (5600 + Math.random() * 7200) / Math.max(intensity, 0.3);
    }

    function draw(now, staticFrame = false) {
        context.clearRect(0, 0, width, height);
        for (const currentLink of topology.links) {
            const faulted = currentLink.state === "fault";
            const recovering = currentLink.state === "rerouting";
            const degraded = currentLink.signal === "degraded";
            const failed = currentLink.signal === "failed";
            drawLink(
                currentLink,
                faulted || failed ? `rgba(248,113,113,${0.92 * intensity})` :
                    degraded ? `rgba(251,191,36,${0.82 * intensity})` :
                        `rgba(96,165,250,${0.3 * intensity})`,
                faulted || failed ? 2.6 : degraded ? 2 : 1.05,
                failed
            );
            if (recovering || (disruption && disruption.link === currentLink && now - disruption.born > 850)) {
                drawLink(currentLink, `rgba(74,222,128,${0.72 * intensity})`, 1.8, true, true);
            }
        }

        for (const packet of packets) {
            const rerouting = packet.link.state === "rerouting" ||
                (disruption && disruption.link === packet.link && now - disruption.born > 850);
            const degraded = packet.link.signal === "degraded";
            const failed = packet.link.signal === "failed";
            if (!staticFrame && packet.link.state !== "fault") {
                packet.progress += packet.speed * packet.direction;
                if (degraded) packet.progress += packet.speed * packet.direction * 0.18;
                if (failed) packet.progress += packet.speed * packet.direction * -0.5;
                if (packet.progress > 1) packet.progress = 0;
                if (packet.progress < 0) packet.progress = 1;
            }
            const { x, y } = curvePoint(packet.link, packet.progress, rerouting);
            const color = rerouting ? "74,222,128" : failed ? "248,113,113" :
                degraded ? "251,191,36" : "56,189,248";
            const glowRadius = failed ? 12 : degraded ? 10 : 8;
            const glow = context.createRadialGradient(x, y, 0, x, y, glowRadius);
            glow.addColorStop(0, `rgba(255,255,255,${(failed || degraded ? 1 : 0.94) * intensity})`);
            glow.addColorStop(0.35, `rgba(${color},${(failed ? 0.9 : degraded ? 0.78 : 0.6) * intensity})`);
            glow.addColorStop(1, `rgba(${color},0)`);
            context.fillStyle = glow;
            context.fillRect(x - glowRadius, y - glowRadius, glowRadius * 2, glowRadius * 2);
        }

        if (!staticFrame && intensity > 0.32 && now >= nextDisruptionAt && !disruption) {
            startFault(now);
        }

        if (disruption) {
            const progress = (now - disruption.born) / disruption.duration;
            if (progress < 1) {
                context.beginPath();
                context.strokeStyle = `rgba(251,146,60,${(1 - progress) * 0.5 * intensity})`;
                context.lineWidth = 1.5;
                context.arc(disruption.node.x, disruption.node.y, 8 + disruption.maxRadius * progress, 0, Math.PI * 2);
                context.stroke();
            } else {
                disruption.link.state = "healthy";
                disruption = null;
            }
        }

        for (const node of topology.nodes) {
            if (node.health === "fault" && now >= node.recoveryUntil - 1400) {
                node.health = "recovering";
            } else if (node.health === "recovering" && now >= node.recoveryUntil) {
                node.health = "healthy";
            }
            if (node.health === "fault" && disruption && now - disruption.born > 850) {
                disruption.link.state = "rerouting";
            }

            const pulse = staticFrame ? 0.72 : 0.62 + Math.sin(now * 0.0015 + node.phase) * 0.38;
            const fault = node.health === "fault";
            const recovering = node.health === "recovering";
            const color = fault ? "248,113,113" : recovering ? "74,222,128" : "125,211,252";
            const haloRadius = (fault ? 25 : recovering ? 21 : 15) * (0.82 + pulse * 0.3);
            const halo = context.createRadialGradient(node.x, node.y, 0, node.x, node.y, haloRadius);
            halo.addColorStop(0, `rgba(${color},${0.7 * pulse * intensity})`);
            halo.addColorStop(1, `rgba(${color},0)`);
            context.fillStyle = halo;
            context.fillRect(node.x - haloRadius, node.y - haloRadius, haloRadius * 2, haloRadius * 2);

            const image = iconImages[node.role];
            const iconSize = width < 720 ? 21 : 28;
            context.save();
            context.fillStyle = "rgba(5,12,25,.8)";
            context.strokeStyle = `rgba(${color},${0.56 * intensity})`;
            context.lineWidth = 1;
            context.beginPath();
            context.arc(node.x, node.y, iconSize * 0.68, 0, Math.PI * 2);
            context.fill();
            context.stroke();
            if (image && image.complete && image.naturalWidth) {
                context.globalAlpha = fault ? 0.66 : 0.38;
                context.drawImage(image, node.x - iconSize / 2, node.y - iconSize / 2, iconSize, iconSize);
            } else {
                context.beginPath();
                context.fillStyle = `rgba(${color},${0.78 + pulse * 0.18})`;
                context.arc(node.x, node.y, 3.4, 0, Math.PI * 2);
                context.fill();
            }
            context.restore();
        }
    }

    function animate(now) {
        if (now - lastFrame >= 33) {
            draw(now);
            lastFrame = now;
        }
        animationFrame = window.requestAnimationFrame(animate);
    }

    function updateMotion() {
        if (animationFrame) window.cancelAnimationFrame(animationFrame);
        animationFrame = null;
        if (reducedMotion.matches) {
            draw(performance.now(), true);
        } else if (!document.hidden) {
            animationFrame = window.requestAnimationFrame(animate);
        }
    }

    let resizeTimer;
    window.addEventListener("resize", () => {
        window.clearTimeout(resizeTimer);
        resizeTimer = window.setTimeout(resize, 160);
    });
    document.addEventListener("visibilitychange", updateMotion);
    reducedMotion.addEventListener?.("change", updateMotion);

    preloadIcons();
    resize();
    nextDisruptionAt = performance.now() + 1800;
    updateMotion();
})();
