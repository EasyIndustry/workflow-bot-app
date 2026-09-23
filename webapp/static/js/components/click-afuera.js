/**
 * Cierra un panel colgante (el de "Avisos" de una fuente, el de
 * notificaciones del marco) al hacer click afuera de su contenedor.
 *
 * No guarda el listener activo en una variable de este módulo: dos paneles
 * —uno por fuente, uno global— pueden estar abiertos a la vez, y un solo
 * "activo" compartido haría que abrir el segundo se llevara puesto el
 * listener del primero. Cada quien que llama se queda con la función que
 * esto devuelve y la usa para sacar su *propio* listener antes de poner
 * otro — cada redibujo arma un contenedor nuevo, y sin sacar el viejo
 * quedaban apuntando a nodos que ya no existen.
 *
 * @returns {() => void} para des-suscribir a mano (opcional: el propio
 *   click afuera ya se des-suscribe solo).
 */
export function alClickAfuera(contenedor, cerrar) {
  const manejador = (e) => {
    if (contenedor.contains(e.target)) return;
    document.removeEventListener("pointerdown", manejador, true);
    cerrar();
  };
  document.addEventListener("pointerdown", manejador, true);
  return () => document.removeEventListener("pointerdown", manejador, true);
}
