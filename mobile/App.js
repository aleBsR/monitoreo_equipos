import React, { useEffect, useState } from 'react';
import { View, Text, TextInput, Pressable, FlatList, StyleSheet, ScrollView } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { NetmonWS, parseNodes, parseRes } from './netmon';

const GRAD = '#E1306C';
const EXECS = ['RESTART_SERVICE', 'DIAGNOSTIC', 'CLEAR_LOGS'];

export default function App() {
  // 👉 ACÁ VA LA IP DE TU PC (la del servidor). La ves con `ipconfig` -> IPv4.
  // Ej. hotspot celu: ws://192.168.43.10:5003 | tu red actual: ws://192.168.252.37:5003
  const [gw, setGw] = useState('ws://192.168.252.37:5003');
  const [user, setUser] = useState('admin');
  const [pass, setPass] = useState('admin123');
  const [cli, setCli] = useState(null);
  const [err, setErr] = useState('');
  const [tab, setTab] = useState('feed');
  const [nodos, setNodos] = useState([]);
  const [info, setInfo] = useState('');
  const [logs, setLogs] = useState([]);
  const [execNodo, setExecNodo] = useState('NODO_01');
  const [execCmd, setExecCmd] = useState('DIAGNOSTIC');
  const [execOut, setExecOut] = useState('');
  const [craft, setCraft] = useState('CMD|ACCION_DESCONOCIDA');

  function log(dir, texto) { setLogs(p => [...p.slice(-99), `${new Date().toLocaleTimeString()} ${dir} ${texto}`]) }

  async function entrar() {
    setErr('');
    const c = new NetmonWS(gw.trim());
    c.onLog = log;
    try {
      await c.connect();
      const r1 = parseRes(await c.cmd('PING'));
      if (r1.status !== 'OK') throw new Error('Gateway no responde PING');
      const r2 = parseRes(await c.cmd('AUTH', user.trim(), pass));
      if (r2.status !== 'OK') throw new Error(`[${r2.code}] ${r2.detail}`);
      setCli(c);
    } catch (e) { setErr(String(e.message || e)) }
  }

  async function refrescar() {
    if (!cli) return;
    try {
      const r = parseRes(await cli.cmd('GET_NODES', 'ALL'));
      if (r.status === 'OK') {
        const l = parseNodes(r.code);
        setNodos(l);
        setInfo(`${l.length} nodos · ${l.filter(n => n.estado !== 'OFFLINE').length} en línea`);
      }
    } catch (e) { setInfo('Error: ' + e.message) }
  }

  useEffect(() => {
    if (!cli) return;
    refrescar();
    const t = setInterval(refrescar, 2000);
    return () => clearInterval(t);
  }, [cli]);

  async function ejecutar() {
    try {
      const r = parseRes(await cli.cmd('EXEC', execNodo, execCmd));
      setExecOut(`[${r.status} ${r.code}] ${r.detail}`);
    } catch (e) { setExecOut('Error: ' + e.message) }
  }

  if (!cli) {
    return (
      <View style={s.login}>
        <StatusBar style="light" />
        <View style={s.hero}>
          <Text style={s.heroTitle}>SDMR 📡</Text>
          <Text style={s.heroSub}>Monitoreo en Red · estilo Instagram</Text>
          <Text style={s.heroHint}>Mismo NETMON/1.0 de Python por gateway WS→TCP</Text>
        </View>
        <View style={s.form}>
          <Text style={s.h}>Iniciar sesión</Text>
          <Text style={s.label}>Gateway = IP DE TU PC + :5003 (editable)</Text>
          <TextInput style={s.in} value={gw} onChangeText={setGw} autoCapitalize="none" placeholder="ws://192.168.252.37:5003" />
          <Text style={s.label}>Usuario</Text>
          <TextInput style={s.in} value={user} onChangeText={setUser} autoCapitalize="none" />
          <Text style={s.label}>Contraseña</Text>
          <TextInput style={s.in} value={pass} onChangeText={setPass} secureTextEntry />
          <Pressable style={s.btn} onPress={entrar}><Text style={s.btnT}>Entrar</Text></Pressable>
          {!!err && <Text style={s.err}>{err}</Text>}
          <Text style={s.hint}>admin/admin123 · Hotspot: cambiá la IP por la de ipconfig</Text>
        </View>
      </View>
    );
  }

  const total = nodos.length;
  const on = nodos.filter(n => n.estado === 'OK').length;
  const off = nodos.filter(n => n.estado === 'OFFLINE').length;

  return (
    <View style={s.app}>
      <StatusBar style="dark" />
      <View style={s.top}>
        <Text style={s.logo}>SDMR</Text>
        <Text style={s.topInfo}>{info}</Text>
        <Pressable onPress={() => { try { cli.close() } catch {} setCli(null) }}><Text style={s.salir}>Salir</Text></Pressable>
      </View>
      <View style={s.tabs}>
        {[['feed', 'Feed'], ['nodos', 'Nodos'], ['trafico', 'Tráfico']].map(([k, l]) => (
          <Pressable key={k} onPress={() => setTab(k)} style={[s.tab, tab === k && s.tabOn]}>
            <Text style={[s.tabT, tab === k && s.tabTOn]}>{l}</Text>
          </Pressable>
        ))}
      </View>
      {tab === 'feed' && (
        <ScrollView style={s.body}>
          <View style={s.kpis}>
            <View style={s.kpi}><Text style={s.kpiN}>{total}</Text><Text>nodos</Text></View>
            <View style={s.kpi}><Text style={[s.kpiN, { color: 'green' }]}>{on}</Text><Text>online</Text></View>
            <View style={s.kpi}><Text style={[s.kpiN, { color: 'red' }]}>{off}</Text><Text>offline</Text></View>
          </View>
          {nodos.map(n => (
            <View key={n.id} style={s.post}>
              <Text style={s.postH}>● {n.id} · {n.ip} · {n.estado}</Text>
              <Text>CPU {n.cpu}% · RAM {n.ram}% · DISK {n.disco}%</Text>
              <View style={s.bar}><View style={[s.fill, { width: `${n.cpu}%` }]} /></View>
            </View>
          ))}
          {nodos.length === 0 && <Text style={s.hint}>Sin nodos. Levantá agentes en las laptops.</Text>}
        </ScrollView>
      )}
      {tab === 'nodos' && (
        <ScrollView style={s.body}>
          <Text style={s.label}>Nodo destino</Text>
          <TextInput style={s.in} value={execNodo} onChangeText={setExecNodo} autoCapitalize="none" />
          <Text style={s.label}>Comando (RESTART_SERVICE / DIAGNOSTIC / CLEAR_LOGS)</Text>
          <TextInput style={s.in} value={execCmd} onChangeText={setExecCmd} autoCapitalize="characters" />
          <Pressable style={s.btn} onPress={ejecutar}><Text style={s.btnT}>Enviar EXEC</Text></Pressable>
          {!!execOut && <Text style={s.hint}>{execOut}</Text>}
          <FlatList data={nodos} keyExtractor={i => i.id} scrollEnabled={false}
            renderItem={({ item }) => <Text style={s.row} onPress={() => setExecNodo(item.id)}>● {item.id} {item.ip} {item.estado} CPU{item.cpu}%</Text>} />
        </ScrollView>
      )}
      {tab === 'trafico' && (
        <ScrollView style={s.body}>
          <Text style={s.label}>Trama manual (RF07)</Text>
          <TextInput style={s.in} value={craft} onChangeText={setCraft} autoCapitalize="none" />
          <Pressable style={s.btn} onPress={async () => { try { const r = await cli.sendRaw(craft.trim()); log('SYS', 'RES: ' + r) } catch (e) { log('SYS', e.message) } }}>
            <Text style={s.btnT}>Enviar</Text></Pressable>
          {logs.slice(-30).map((l, i) => <Text key={i} style={s.mono}>{l}</Text>)}
        </ScrollView>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  login: { flex: 1, backgroundColor: '#fafafa' },
  hero: { backgroundColor: '#833AB4', padding: 36, paddingTop: 64 },
  heroTitle: { color: '#fff', fontSize: 34, fontWeight: '900' },
  heroSub: { color: '#fff', fontSize: 15, marginTop: 4 },
  heroHint: { color: '#fff', opacity: 0.85, marginTop: 8, fontSize: 12 },
  form: { padding: 22 },
  h: { fontSize: 22, fontWeight: '800', marginBottom: 10 },
  label: { fontSize: 12, color: '#8e8e8e', marginTop: 10 },
  in: { borderWidth: 1, borderColor: '#dbdbdb', borderRadius: 10, padding: 10, backgroundColor: '#fff', marginTop: 4 },
  btn: { backgroundColor: GRAD, borderRadius: 10, padding: 13, marginTop: 16, alignItems: 'center' },
  btnT: { color: '#fff', fontWeight: '800' },
  err: { backgroundColor: '#fdecea', color: '#9c1c1c', padding: 10, borderRadius: 10, marginTop: 10 },
  hint: { color: '#8e8e8e', fontSize: 12, marginTop: 8 },
  app: { flex: 1, backgroundColor: '#fafafa', paddingTop: 44 },
  top: { flexDirection: 'row', alignItems: 'center', padding: 12, backgroundColor: '#fff', borderBottomWidth: 1, borderColor: '#dbdbdb' },
  logo: { fontWeight: '900', fontSize: 20, color: GRAD },
  topInfo: { flex: 1, fontSize: 11, color: '#8e8e8e', marginLeft: 10 },
  salir: { color: GRAD, fontWeight: '700' },
  tabs: { flexDirection: 'row', backgroundColor: '#fff', borderBottomWidth: 1, borderColor: '#dbdbdb' },
  tab: { flex: 1, padding: 12, alignItems: 'center' },
  tabOn: { borderBottomWidth: 2, borderColor: GRAD },
  tabT: { color: '#8e8e8e', fontWeight: '600' },
  tabTOn: { color: '#262626', fontWeight: '800' },
  body: { padding: 12 },
  kpis: { flexDirection: 'row', gap: 8, marginBottom: 10 },
  kpi: { flex: 1, backgroundColor: '#fff', borderWidth: 1, borderColor: '#dbdbdb', borderRadius: 14, padding: 12, alignItems: 'center' },
  kpiN: { fontSize: 22, fontWeight: '900' },
  post: { backgroundColor: '#fff', borderWidth: 1, borderColor: '#dbdbdb', borderRadius: 14, padding: 12, marginBottom: 10 },
  postH: { fontWeight: '800', marginBottom: 4 },
  bar: { height: 8, backgroundColor: '#eee', borderRadius: 99, marginTop: 6 },
  fill: { height: 8, backgroundColor: GRAD, borderRadius: 99 },
  row: { padding: 10, backgroundColor: '#fff', borderWidth: 1, borderColor: '#eee', borderRadius: 10, marginTop: 6 },
  mono: { fontFamily: 'monospace', fontSize: 11, backgroundColor: '#111', color: '#9f9', padding: 6, borderRadius: 6, marginTop: 4 }
});
