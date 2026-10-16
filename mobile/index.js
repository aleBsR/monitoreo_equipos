import { registerRootComponent } from 'expo';

import App from './App';

// Registra el componente raiz con el nombre 'main'.
// Sin esto, Expo Go compila el bundle pero al correrlo falla con:
// "main" has not been registered (AppRegistry.registerComponent nunca se llamo).
registerRootComponent(App);
