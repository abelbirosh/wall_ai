function Button(props: { onClick: () => void }) {
  return <button onClick={props.onClick}>Refresh</button>;
}

export default Button;
