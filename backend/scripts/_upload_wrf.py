import paramiko, sys, time, os

sys.stdout.reconfigure(encoding="utf-8")
LOCAL = sys.argv[1]
REMOTE = sys.argv[2]
CHUNK = 32 * 1024 * 1024  # 32 Mo
MAX_RECONNECTS = 500  # le serveur a des fenetres d'indisponibilite intermittentes (quelques
                       # minutes a la fois, cause externe non identifiee) -- on reste patient.

total = os.path.getsize(LOCAL)
t0 = time.time()
reconnects = 0
known_offset = 0  # progres confirme par NOUS (ecritures reussies dans ce run) ; plus fiable
                   # qu'un stat() distant qui peut repondre "absent" par erreur passagere.


def stat_size_retrying(sftp, path, tries=3, pause=3):
    last_exc = None
    for _ in range(tries):
        try:
            return sftp.stat(path).st_size
        except FileNotFoundError as e:
            last_exc = e
            time.sleep(pause)
    raise last_exc


while True:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect("197.239.116.77", username="citadelle", password="citadelle", timeout=20,
                       look_for_keys=False, allow_agent=False, banner_timeout=30, auth_timeout=30)
        client.get_transport().set_keepalive(15)
        sftp = client.open_sftp()

        if known_offset > 0:
            offset = known_offset
        else:
            try:
                offset = stat_size_retrying(sftp, REMOTE)
            except FileNotFoundError:
                offset = 0

        if offset >= total:
            print(f"Deja complet ({offset} octets), rien a faire.")
            break

        mode = "ab" if offset > 0 else "wb"
        print(f"[connexion] reprise a {offset/1e6:.1f} / {total/1e6:.1f} Mo (mode {mode})", flush=True)

        sent = offset
        last_t = time.time()
        with open(LOCAL, "rb") as lf, sftp.open(REMOTE, mode) as rf:
            rf.set_pipelined(True)
            lf.seek(offset)
            while True:
                data = lf.read(CHUNK)
                if not data:
                    break
                rf.write(data)
                sent += len(data)
                known_offset = sent
                now = time.time()
                if now - last_t > 10:
                    mb_s = (sent - offset) / (now - t0) / 1e6 if now > t0 else 0
                    print(f"{sent/1e6:8.1f} / {total/1e6:.1f} Mo  ({100*sent/total:4.1f}%)  ~{mb_s:.1f} Mo/s", flush=True)
                    last_t = now

        print(f"Termine en {time.time()-t0:.0f}s, {sent} octets envoyes au total")
        break
    except Exception as e:
        reconnects += 1
        print(f"[reconnexion {reconnects}] echec: {e!r} (progres conserve: {known_offset/1e6:.1f} Mo)", flush=True)
        if reconnects >= MAX_RECONNECTS:
            print("Abandon apres le nombre maximal de reconnexions.", flush=True)
            raise
        time.sleep(15)
    finally:
        try:
            client.close()
        except Exception:
            pass
