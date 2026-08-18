# WSL -> Windows CDP bridge: listen 0.0.0.0:9224, forward to 127.0.0.1:9222
# Raw TCP relay (works for HTTP + WebSocket).
$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Any, 9224)
$listener.Start()
Write-Output "relay listening on 0.0.0.0:9224 -> 127.0.0.1:9222"
while ($true) {
    try {
        $client = $listener.AcceptTcpClient()
        $upstream = [System.Net.Sockets.TcpClient]::new("127.0.0.1", 9222)
        $clientStream = $client.GetStream()
        $upstreamStream = $upstream.GetStream()
        # two-way pump
        $jobs = @()
        $jobs += [System.Threading.Tasks.Task]::Run({
            param($a, $b)
            try { $a.CopyTo($b) } catch {}
            try { $b.Close() } catch {}
        }, @($clientStream, $upstreamStream))
        $jobs += [System.Threading.Tasks.Task]::Run({
            param($a, $b)
            try { $a.CopyTo($b) } catch {}
            try { $a.Close() } catch {}
        }, @($upstreamStream, $clientStream))
        [System.Threading.Tasks.Task]::WaitAll($jobs) | Out-Null
        $client.Close()
    } catch {}
}
