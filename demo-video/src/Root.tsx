import { Composition } from "remotion";
import { Demo } from "./Demo";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="AIOMNI"
        component={Demo}
        durationInFrames={1770}
        fps={30}
        width={1920}
        height={1080}
      />
    </>
  );
};
