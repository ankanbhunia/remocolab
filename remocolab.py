import apt, apt.debfile
import pathlib, stat, shutil, urllib.request, subprocess, getpass, time
import secrets, json, re
import IPython.utils.io
import os, ssl
if (not os.environ.get('PYTHONHTTPSVERIFY', '') and getattr(ssl, '_create_unverified_context', None)):
  ssl._create_default_https_context = ssl._create_unverified_context

def _installPkg(cache, name):
  pkg = cache[name]
  if not pkg.is_installed:
    
 
    pkg.mark_install()

def _installPkgs(cache, *args):
  for i in args:
    _installPkg(cache, i)

def _download(url, path):
  try:
    with urllib.request.urlopen(url) as response:
      with open(path, 'wb') as outfile:
        shutil.copyfileobj(response, outfile)
  except:
    print("Failed to download ", url)
    raise

def _get_gpu_name():
  r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], stdout = subprocess.PIPE, universal_newlines = True)
  if r.returncode != 0:
    return None
  return r.stdout.strip()

def _check_gpu_available():
  gpu_name = _get_gpu_name()
  if gpu_name == None:
    print("This is not a runtime with GPU")
  elif gpu_name == "Tesla K80":
    print("Warning! GPU of your assigned virtual machine is Tesla K80.")
    print("You might get better GPU by reseting the runtime.")
  else:
    return True

  return IPython.utils.io.ask_yes_no("Do you want to continue? [y/n]")

def _setupSSHDImpl(ngrok_token, ngrok_region, password):

  #Prevent ssh session disconnection.
  get_ipython().system_raw('wget -q -c -nc https://bin.equinox.io/c/4VmDzA7iaHb/ngrok-stable-linux-amd64.zip -O /content/Colab/ngrok.zip')
  get_ipython().system_raw('unzip -qq -n /content/Colab/ngrok.zip -d /content/Colab/')
  #Setup sshd
  get_ipython().system_raw('apt-get install -qq -o=Dpkg::Use-Pty=0 openssh-server pwgen > /dev/null')
  #Set root password
  
  get_ipython().system_raw('echo root:$password | chpasswd')
  get_ipython().system_raw('mkdir -p /var/run/sshd')
  get_ipython().system_raw('echo "PermitRootLogin yes" >> /etc/ssh/sshd_config')
  get_ipython().system_raw('echo "PasswordAuthentication yes" >> /etc/ssh/sshd_config')
  get_ipython().system_raw('echo "LD_LIBRARY_PATH=/usr/lib64-nvidia" >> /root/.bashrc')
  get_ipython().system_raw('echo "export LD_LIBRARY_PATH" >> /root/.bashrc')

  #Run sshd
  get_ipython().system_raw('/usr/sbin/sshd -D &')
  if not pathlib.Path('/root/.ngrok2/ngrok.yml').exists():
    subprocess.run(["/content/Colab/ngrok", "authtoken", ngrok_token])

  ngrok_proc = subprocess.Popen(["/content/Colab/ngrok", "tcp", "-region", ngrok_region, "22"])
  time.sleep(2)
  if ngrok_proc.poll() != None:
    raise RuntimeError("Failed to run ngrok. Return code:" + str(ngrok_proc.returncode) + "\nSee runtime log for more info.")

  with urllib.request.urlopen("http://localhost:4040/api/tunnels") as response:
    url = json.load(response)['tunnels'][0]['public_url']
    m = re.match("tcp://(.+):(\d+)", url)

  hostname = m.group(1)
  port = m.group(2)

  ssh_common_options =  "-o UserKnownHostsFile=/dev/null -o VisualHostKey=yes"
  
  print("(A) SSH server:->> [type the command in your terminal] ")

  print(f"ssh {ssh_common_options} -p {port} root@{hostname}")

  print("(B) VNC server:->> [Run the command for desktop interface. Then, open TurboVNC viewer and use the following password]")
 
  print(f"ssh {ssh_common_options} -L 5901:localhost:5901 -p {port} root@{hostname}")
  

def setupSSHD(ngrok_token = None, ngrok_region = None, password = None, check_gpu_available = False):
  if check_gpu_available and not _check_gpu_available():
    return False

  #Set your ngrok Authtoken.
  #ngrok_token = getpass.getpass()

  if not ngrok_region:
    print("Select your ngrok region:")
    print("us - United States (Ohio)")
    print("eu - Europe (Frankfurt)")
    print("ap - Asia/Pacific (Singapore)")
    print("au - Australia (Sydney)")
    print("sa - South America (Sao Paulo)")
    print("jp - Japan (Tokyo)")
    print("in - India (Mumbai)")
    ngrok_region = region = input()

  _setupSSHDImpl(ngrok_token, ngrok_region, password)
  return True

def _setup_nvidia_gl():
  # Install TESLA DRIVER FOR LINUX X64.
  # Kernel module in this driver is already loaded and cannot be neither removed nor updated.
  # (nvidia, nvidia_uvm, nvidia_drm. See dmesg)
  # Version number of nvidia driver for Xorg must match version number of these kernel module.
  # But existing nvidia driver for Xorg might not match.
  # So overwrite them with the nvidia driver that is same version to loaded kernel module.
  ret = subprocess.run(
                  ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                  stdout = subprocess.PIPE,
                  check = True,
                  universal_newlines = True)
  nvidia_version = ret.stdout.strip()
  nvidia_url = "https://us.download.nvidia.com/tesla/{0}/NVIDIA-Linux-x86_64-{0}.run".format(nvidia_version)
  _download(nvidia_url, "nvidia.run")
  pathlib.Path("nvidia.run").chmod(stat.S_IXUSR)
  subprocess.run(["./nvidia.run", "--no-kernel-module", "--ui=none"], input = "1\n", check = True, universal_newlines = True)

  #https://virtualgl.org/Documentation/HeadlessNV
  subprocess.run(["nvidia-xconfig",
                  "-a",
                  "--allow-empty-initial-configuration",
                  "--virtual=1920x1200",
                  "--busid", "PCI:0:4:0"],
                 check = True
                )

  with open("/etc/X11/xorg.conf", "r") as f:
    conf = f.read()
    conf = re.sub('(Section "Device".*?)(EndSection)',
                  '\\1    MatchSeat      "seat-1"\n\\2',
                  conf,
                  1,
                  re.DOTALL)
  #  conf = conf + """
  #Section "Files"
  #    ModulePath "/usr/lib/xorg/modules"
  #    ModulePath "/usr/lib/x86_64-linux-gnu/nvidia-418/xorg/"
  #EndSection
  #"""

  with open("/etc/X11/xorg.conf", "w") as f:
    f.write(conf)

  #!service lightdm stop
  subprocess.run(["/opt/VirtualGL/bin/vglserver_config", "-config", "+s", "+f"], check = True)
  #user_name = "colab"
  #!usermod -a -G vglusers $user_name
  #!service lightdm start

  # Run Xorg server
  # VirtualGL and OpenGL application require Xorg running with nvidia driver to get Hardware 3D Acceleration.
  #
  # Without "-seat seat-1" option, Xorg try to open /dev/tty0 but it doesn't exists.
  # You can create /dev/tty0 with "mknod /dev/tty0 c 4 0" but you will get permision denied error.
  subprocess.Popen(["Xorg", "-seat", "seat-1", "-allowMouseOpenFail", "-novtswitch", "-nolisten", "tcp"])

def _setupVNC():
  libjpeg_ver = "2.0.3"
  virtualGL_ver = "2.6.2"
  turboVNC_ver = "2.2.3"

  libjpeg_url = "https://svwh.dl.sourceforge.net/project/libjpeg-turbo/{0}/libjpeg-turbo-official_{0}_amd64.deb".format(libjpeg_ver)
  virtualGL_url = "https://svwh.dl.sourceforge.net/project/virtualgl/{0}/virtualgl_{0}_amd64.deb".format(virtualGL_ver)
  turboVNC_url = "https://svwh.dl.sourceforge.net/project/turbovnc/{0}/turbovnc_{0}_amd64.deb".format(turboVNC_ver)

  _download(libjpeg_url, "libjpeg-turbo.deb")
  _download(virtualGL_url, "virtualgl.deb")
  _download(turboVNC_url, "turbovnc.deb")
  cache = apt.Cache()
  apt.debfile.DebPackage("libjpeg-turbo.deb", cache).install()
  apt.debfile.DebPackage("virtualgl.deb", cache).install()
  apt.debfile.DebPackage("turbovnc.deb", cache).install()

  _installPkgs(cache, "xfce4", "xfce4-terminal")
  cache.commit()

  vnc_sec_conf_p = pathlib.Path("/etc/turbovncserver-security.conf")
  vnc_sec_conf_p.write_text("""\
no-remote-connections
no-httpd
no-x11-tcp-connections
""")

  gpu_name = _get_gpu_name()
  if gpu_name != None:
    _setup_nvidia_gl()

  vncrun_py = pathlib.Path("vncrun.py")
  vncrun_py.write_text("""\
import subprocess, secrets, pathlib
vnc_passwd = secrets.token_urlsafe()[:8]
vnc_viewonly_passwd = secrets.token_urlsafe()[:8]
print("#"*24)
print("VNC password: {}".format(vnc_passwd))
print("VNC view only password: {}".format(vnc_viewonly_passwd))
print("#"*24)
vncpasswd_input = "{0}\\n{1}".format(vnc_passwd, vnc_viewonly_passwd)
vnc_user_dir = pathlib.Path.home().joinpath(".vnc")
vnc_user_dir.mkdir(exist_ok=True)
vnc_user_passwd = vnc_user_dir.joinpath("passwd")
with vnc_user_passwd.open('wb') as f:
  subprocess.run(
    ["/opt/TurboVNC/bin/vncpasswd", "-f"],
    stdout=f,
    input=vncpasswd_input,
    universal_newlines=True)
vnc_user_passwd.chmod(0o600)
subprocess.run(
  ["/opt/TurboVNC/bin/vncserver"]
)
#Disable screensaver because no one would want it.
(pathlib.Path.home() / ".xscreensaver").write_text("mode: off\\n")
""")
  txt = get_ipython().getoutput('python3 vncrun.py')[1:3]
  print (txt[0])
  print (txt[1])
 

def setupVNC(ngrok_token = None, ngrok_region = None, password = None):
  if setupSSHD(ngrok_token, ngrok_region,password, True):
    _setupVNC()
