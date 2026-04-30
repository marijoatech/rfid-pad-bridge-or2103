# rfid-bridge-or2103

Bridge común para OR2103.

## PHP

Llamar siempre:

```text
PADBridge.php?action=status
PADBridge.php?action=read-epc
PADBridge.php?action=inventory
PADBridge.php?action=write-epc&epc=000000000000000001000026
PADBridge.php?action=clear&palabras=6
```

## Windows

Usa:

```text
windows/OR2103Bridge.exe
windows/OR2127LIB.dll
```

## Linux

Requisito:

```bash
apt install python3-serial -y
chmod 666 /dev/ttyUSB0
```

Pruebas:

```bash
python3 linux/OR2103Bridge.py status
python3 linux/OR2103Bridge.py read-epc
python3 linux/OR2103Bridge.py inventory
```
 
